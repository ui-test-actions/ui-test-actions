"""Bounded read-only snapshots; no breakpoints, register writes or signal changes."""
import datetime
import json
import os
import re
import time
import lldb


def stamp():
    return dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), monotonic_ns=time.monotonic_ns())


def capture(debugger, output_path):
    debugger.SetAsync(True)
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    with open(output_path, 'w', buffering=1) as output:
        def emit(kind, **fields):
            output.write(json.dumps(dict(kind=kind, **stamp(), **fields)) + '\n')

        def region(address):
            info = lldb.SBMemoryRegionInfo()
            err = process.GetMemoryRegionInfo(address, info)
            return dict(address=hex(address), error=str(err), start=hex(info.GetRegionBase()),
                        end=hex(info.GetRegionEnd()), read=info.IsReadable(),
                        write=info.IsWritable(), execute=info.IsExecutable(), mapped=info.IsMapped(), name=info.GetName())

        def snapshot(label):
            # Reacquire objects after every stop; never use selected-frame CLI PC.
            p = target.GetProcess()
            emit('snapshot', label=label, pid=p.GetProcessID(), state=p.GetState(), stop_id=p.GetStopID())
            if p.GetState() not in (lldb.eStateStopped, lldb.eStateCrashed):
                return
            threads = list(p)
            faults = [t for t in threads if t.GetStopReason() in (lldb.eStopReasonSignal, lldb.eStopReasonException)]
            chosen = faults[:4] or [p.GetSelectedThread()]
            emit('threads', count=len(threads), stopped=[dict(tid=t.GetThreadID(), reason=t.GetStopReason(), description=t.GetStopDescription(512)) for t in threads if t.GetStopReason() != lldb.eStopReasonNone][:16])
            for t in chosen:
                frame = t.GetFrameAtIndex(0)
                pc = frame.GetPC()
                desc = t.GetStopDescription(512) or ''
                emit('frame', tid=t.GetThreadID(), pc=hex(pc), description=desc,
                     reason=t.GetStopReason(), reason_data=[t.GetStopReasonDataAtIndex(i) for i in range(t.GetStopReasonDataCount())],
                     stack=[dict(pc=hex(f.GetPC()), function=f.GetFunctionName()) for f in list(t)[:8]])
                regs = frame.GetRegisters()
                emit('registers', tid=t.GetThreadID(), pc=hex(pc), sets=[dict(name=r.GetName(), values={v.GetName():v.GetValue() for v in r}) for r in regs if 'general' in (r.GetName() or '').lower()])
                err = lldb.SBError()
                raw = p.ReadMemory(pc, 64, err)
                emit('code', tid=t.GetThreadID(), pc=hex(pc), error=str(err), raw_hex=raw.hex(), region=region(pc))
                # Decode precisely the bytes read from this stopped process, at this numeric PC.
                instructions = target.GetInstructions(lldb.SBAddress(pc, target), raw)
                decoded = []
                for ins in list(instructions)[:12]:
                    data = ins.GetData(target)
                    e = lldb.SBError()
                    octets = bytes(data.GetUnsignedInt8(e, i) for i in range(data.GetByteSize()))
                    decoded.append(dict(address=hex(ins.GetAddress().GetLoadAddress(target)), raw_hex=octets.hex(), mnemonic=ins.GetMnemonic(target), operands=ins.GetOperands(target)))
                emit('decode', tid=t.GetThreadID(), pc=hex(pc), instructions=decoded,
                     first_matches=bool(decoded and decoded[0]['address']==hex(pc) and raw.hex().startswith(decoded[0]['raw_hex'])))
                # Independent explicit-address CLI output for audit; no --pc or memory region --all.
                result = lldb.SBCommandReturnObject()
                debugger.GetCommandInterpreter().HandleCommand('disassemble --start-address %s --count 8 --bytes' % hex(pc), result)
                emit('numeric_disassembly', pc=hex(pc), output=result.GetOutput(), error=result.GetError())
                for address in set(int(x,16) for x in re.findall(r'0x[0-9a-fA-F]+', desc)):
                    emit('fault_region', tid=t.GetThreadID(), region=region(address))

        snapshot('after-attach')
        if process.GetState() == lldb.eStateStopped:
            previous = process.GetStopID()
            emit('continue', error=str(process.Continue()))
            start = time.monotonic()
            for delay in (0.25, 1.0, 3.0):
                while time.monotonic()-start < delay:
                    state = process.GetState()
                    if state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached) or (state == lldb.eStateStopped and process.GetStopID() != previous):
                        break
                    time.sleep(0.01)
                state = process.GetState()
                natural = state != lldb.eStateRunning
                if not natural:
                    emit('observer_interrupt', error=str(process.Stop()), elapsed=time.monotonic()-start)
                    for _ in range(100):
                        if process.GetState() != lldb.eStateRunning:
                            break
                        time.sleep(0.01)
                snapshot('natural-stop' if natural else 'timed-sample-%.2f' % delay)
                if natural or process.GetState() != lldb.eStateStopped:
                    break
                previous = process.GetStopID()
                emit('continue', error=str(process.Continue()))
        if process.GetState() in (lldb.eStateStopped, lldb.eStateCrashed):
            emit('detach', error=str(process.Detach()))
        emit('final', state=process.GetState(), pid=process.GetProcessID())

capture(lldb.debugger, os.environ['NATIVE_OBSERVATION_FILE'])
