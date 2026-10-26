// Dump decompilation of key functions and cross-references to the
// PlayerProfile singleton. Run with:
//   analyzeHeadless <proj> SJF -process -noanalysis -scriptPath <dir> -postScript DumpTargets.java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.util.task.ConsoleTaskMonitor;

public class DumpTargets extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = {
            0x4ff5dcL, // ANativeActivity_onCreate
            0x4fed2cL, // lifecycle command dispatcher
            0x4ff5c0L, // caller in the worker-thread backtrace
            0x32c7a8L, // PlayerProfile::triggerStartCount
            0x330798L, // PlayerProfile ctor-ish
        };
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        for (long t : targets) {
            Address a = toAddr(t);
            Function f = getFunctionContaining(a);
            println("=== 0x" + Long.toHexString(t) + " -> " + (f == null ? "none" : f.getName()));
            if (f != null) {
                DecompileResults r = dec.decompileFunction(f, 90, mon);
                if (r != null && r.decompileCompleted()) {
                    String c = r.getDecompiledFunction().getC();
                    println(c.length() > 6000 ? c.substring(0, 6000) : c);
                }
            }
        }
        for (long d : new long[]{0x5cbed0L, 0x5bd130L}) {
            println("=== xrefs to 0x" + Long.toHexString(d));
            for (Reference r : getReferencesTo(toAddr(d))) {
                Function f = getFunctionContaining(r.getFromAddress());
                println("   from " + r.getFromAddress() + " " + r.getReferenceType()
                        + " in " + (f == null ? "?" : f.getName()));
            }
        }
    }
}
