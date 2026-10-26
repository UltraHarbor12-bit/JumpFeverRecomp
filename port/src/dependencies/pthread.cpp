// Host module: pthread + sem (guest threads get their own JIT)
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/runtime.h"

#include <condition_variable>
#include <map>
#include <memory>
#include <mutex>
#include <thread>

namespace sjf {

namespace {
struct Mutex {
    std::mutex m;
};
struct Cond {
    std::condition_variable cv;
    std::mutex m;
};
struct Sem {
    std::mutex m;
    std::condition_variable cv;
    int count = 0;
};
std::map<u64, std::unique_ptr<Mutex>> g_mutexes;
std::map<u64, std::unique_ptr<Cond>> g_conds;
std::map<u64, std::unique_ptr<Sem>> g_sems;
std::map<u64, std::unique_ptr<std::mutex>> g_mutex_guard;
std::mutex g_registry;

Mutex* mutex_at(u64 gaddr) {
    std::lock_guard<std::mutex> lk(g_registry);
    auto it = g_mutexes.find(gaddr);
    if (it == g_mutexes.end())
        it = g_mutexes.emplace(gaddr, std::make_unique<Mutex>()).first;
    return it->second.get();
}
Cond* cond_at(u64 gaddr) {
    std::lock_guard<std::mutex> lk(g_registry);
    auto it = g_conds.find(gaddr);
    if (it == g_conds.end())
        it = g_conds.emplace(gaddr, std::make_unique<Cond>()).first;
    return it->second.get();
}
Sem* sem_at(u64 gaddr) {
    std::lock_guard<std::mutex> lk(g_registry);
    auto it = g_sems.find(gaddr);
    if (it == g_sems.end())
        it = g_sems.emplace(gaddr, std::make_unique<Sem>()).first;
    return it->second.get();
}

// pthread_key -> per-thread u64 value
std::map<int, std::map<std::thread::id, u64>> g_keys;
std::mutex g_key_mutex;
} // namespace

void register_pthread_module() {
    // ---- threads ----
    register_host_fn("pthread_create", [](GuestCall& c) {
        // (pthread_t*, attr*, start_routine, arg)
        u64 routine = c.x[2], arg = c.x[3];
        LOGD("pthread_create(routine=0x%llx)", (unsigned long long)routine);
        bool ok = guest_thread_start(routine, arg);
        if (c.x[0]) {
            u64 handle = (u64)(ok ? 1 : 0);
            gwrite(c.x[0], &handle, 8);
        }
        c.ret = ok ? 0 : 11; // EAGAIN
    });
    register_host_fn("pthread_attr_init", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("pthread_attr_setdetachstate", [](GuestCall& c) { c.ret = 0; });

    // ---- mutexes ----
    register_host_fn("pthread_mutex_init", [](GuestCall& c) {
        mutex_at(c.x[0]);
        c.ret = 0;
    });
    register_host_fn("pthread_mutex_destroy", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("pthread_mutex_lock", [](GuestCall& c) {
        mutex_at(c.x[0])->m.lock();
        c.ret = 0;
    });
    register_host_fn("pthread_mutex_unlock", [](GuestCall& c) {
        mutex_at(c.x[0])->m.unlock();
        c.ret = 0;
    });

    // ---- condvars ----
    register_host_fn("pthread_cond_init", [](GuestCall& c) {
        cond_at(c.x[0]);
        c.ret = 0;
    });
    register_host_fn("pthread_cond_destroy", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("pthread_cond_wait", [](GuestCall& c) {
        Cond* cv = cond_at(c.x[0]);
        Mutex* mu = mutex_at(c.x[1]);
        std::unique_lock<std::mutex> lk(mu->m, std::adopt_lock);
        cv->cv.wait(lk);
        lk.release(); // keep it locked for the guest (POSIX semantics)
        c.ret = 0;
    });
    register_host_fn("pthread_cond_broadcast", [](GuestCall& c) {
        cond_at(c.x[0])->cv.notify_all();
        c.ret = 0;
    });

    // ---- thread-local storage ----
    register_host_fn("pthread_key_create", [](GuestCall& c) {
        static int next = 1;
        std::lock_guard<std::mutex> lk(g_key_mutex);
        int key = next++;
        if (c.x[0]) { int k = key; gwrite(c.x[0], &k, 4); }
        c.ret = 0;
    });
    register_host_fn("pthread_key_delete", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("pthread_setspecific", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_key_mutex);
        g_keys[(int)(i32)c.x[0]][std::this_thread::get_id()] = c.x[1];
        c.ret = 0;
    });
    register_host_fn("pthread_getspecific", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_key_mutex);
        auto& per = g_keys[(int)(i32)c.x[0]];
        auto it = per.find(std::this_thread::get_id());
        c.ret = it == per.end() ? 0 : it->second;
    });

    // ---- once ----
    register_host_fn("pthread_once", [](GuestCall& c) {
        // (pthread_once_t* once, void (*init)(void))
        u64 guard = c.x[0], fn = c.x[1];
        if (!guard || !fn) { c.ret = 0; return; }
        i32 flag = 0;
        gread(&flag, guard, 4);
        if (flag == 2) { c.ret = 0; return; } // already done
        i32 inprogress = 1;
        gwrite(guard, &inprogress, 4);
        guest_call_nested(fn);
        i32 done = 2;
        gwrite(guard, &done, 4);
        c.ret = 0;
    });

    // ---- semaphores ----
    register_host_fn("sem_init", [](GuestCall& c) {
        Sem* s = sem_at(c.x[0]);
        std::lock_guard<std::mutex> lk(s->m);
        s->count = (int)(i32)c.x[2];
        c.ret = 0;
    });
    register_host_fn("sem_destroy", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("sem_post", [](GuestCall& c) {
        Sem* s = sem_at(c.x[0]);
        {
            std::lock_guard<std::mutex> lk(s->m);
            ++s->count;
        }
        s->cv.notify_one();
        c.ret = 0;
    });
    register_host_fn("sem_trywait", [](GuestCall& c) {
        Sem* s = sem_at(c.x[0]);
        std::lock_guard<std::mutex> lk(s->m);
        if (s->count > 0) { --s->count; c.ret = 0; }
        else c.ret = 11; // EAGAIN
    });
}

} // namespace sjf
