import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

old = '''                                       LOGI("SL player->GetInterface(%s)", iid2.c_str());
                                       // SLPlayItf: SetPlayState=0, GetPlayState=1...
                                       u64 itf2 = make_interface("SLPlay", 8, {
                                           {0, [](GuestCall& cc) {                   // SetPlayState
                                                LOGI("SL Play::SetPlayState(%u)", (unsigned)cc.x[1]);
                                                cc.ret = SL_RESULT_SUCCESS; }},
                                           {1, [](GuestCall& cc) {                   // GetPlayState
                                                if (cc.x[1]) { u32 st = 3 /*playing*/; gwrite(cc.x[1], &st, 4); }
                                                cc.ret = SL_RESULT_SUCCESS; }},
                                       });
                                       if (cc.x[2]) gwrite(cc.x[2], &itf2, 8);'''

new = '''                                       LOGI("SL player->GetInterface(%s)", iid2.c_str());
                                       u64 itf2 = 0;
                                       if (iid2 == "SL_IID_PLAY") {
                                           // SLPlayItf: 0=SetPlayState 1=GetPlayState 2=GetDuration
                                           // 3=GetPosition 4=RegisterCallback 5=SetCallbackEventsMask
                                           // 6=SetPositionUpdatePeriod 7=GetPositionUpdatePeriod
                                           itf2 = make_interface("SLPlay", 8, {
                                               {0, [](GuestCall& cc) {
                                                    LOGI("SL Play::SetPlayState(%u)", (unsigned)cc.x[1]);
                                                    cc.ret = SL_RESULT_SUCCESS; }},
                                               {1, [](GuestCall& cc) {
                                                    if (cc.x[1]) { u32 st = 3; gwrite(cc.x[1], &st, 4); }
                                                    cc.ret = SL_RESULT_SUCCESS; }},
                                               {3, [](GuestCall& cc) {
                                                    if (cc.x[1]) { u32 ms = 0; gwrite(cc.x[1], &ms, 4); }
                                                    cc.ret = SL_RESULT_SUCCESS; }},
                                           });
                                       } else if (iid2 == "SL_IID_BUFFERQUEUE") {
                                           // SLBufferQueueItf: 0=Enqueue 1=Clear 2=GetState 3=RegisterCallback
                                           itf2 = make_interface("SLBufferQueue", 8, {
                                               {0, [](GuestCall& cc) {
                                                    static int ne = 0;
                                                    if (ne++ < 10)
                                                        LOGI("SL BufferQueue::Enqueue(size=%u)",
                                                             (unsigned)cc.x[2]);
                                                    cc.ret = SL_RESULT_SUCCESS; }},
                                               {3, [](GuestCall& cc) {
                                                    LOGI("SL BufferQueue::RegisterCallback(0x%llx)",
                                                         (unsigned long long)cc.x[1]);
                                                    cc.ret = SL_RESULT_SUCCESS; }},
                                           });
                                       } else if (iid2 == "SL_IID_VOLUME") {
                                           // SLVolumeItf: 0=SetVolume 1=GetVolume 3=SetMute 4=GetMute
                                           itf2 = make_interface("SLVolume", 9, {
                                               {0, [](GuestCall& cc) { cc.ret = SL_RESULT_SUCCESS; }},
                                               {3, [](GuestCall& cc) { cc.ret = SL_RESULT_SUCCESS; }},
                                           });
                                       } else if (iid2 == "SL_IID_PLAYBACKRATE") {
                                           // SLPlaybackRateItf: 0=SetRate 1=GetRate 2=SetPropertyConstraints 3=GetProperties
                                           itf2 = make_interface("SLPlaybackRate", 4, {
                                               {0, [](GuestCall& cc) { cc.ret = SL_RESULT_SUCCESS; }},
                                               {1, [](GuestCall& cc) {
                                                    if (cc.x[1]) { u32 r = 1000; gwrite(cc.x[1], &r, 4); }
                                                    cc.ret = SL_RESULT_SUCCESS; }},
                                           });
                                       }
                                       if (cc.x[2]) gwrite(cc.x[2], &itf2, 8);'''

if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('iid dispatch added')
else:
    print('PATTERN MISS')
