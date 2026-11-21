"""LLDB observation only: registers, stack, instructions, mappings, then detach."""
import json
import os
import time

import lldb

output_path = os.environ["NATIVE_OBSERVATION_FILE"]
debugger = lldb.debugger
debugger.SetAsync(True)
target = debugger.GetSelectedTarget()
process = target.GetProcess()
interpreter = debugger.GetCommandInterpreter()


def command(output, text):
    result = lldb.SBCommandReturnObject()
    interpreter.HandleCommand(text, result)
    output.write("\nCOMMAND " + text + "\n")
    output.write(result.GetOutput() or "")
    output.write(result.GetError() or "")


def snapshot(output, label):
    output.write("\nSNAPSHOT " + label + "\n")
    output.write("state=" + str(process.GetState()) + " pid=" + str(process.GetProcessID()) + "\n")
    command(output, "thread list")
    command(output, "thread backtrace all -c 20")
    command(output, "register read")
    command(output, "disassemble --pc --count 16")
    command(output, "memory region --all")
    command(output, "image list")
    output.flush()


with open(output_path, "w") as output:
    snapshot(output, "after-attach")
    if process.GetState() == lldb.eStateStopped:
        error = process.Continue()
        output.write("continue=" + str(error) + "\n")
        deadline = time.monotonic() + 8
        observed_running = False
        while time.monotonic() < deadline:
            state = process.GetState()
            if state == lldb.eStateRunning:
                observed_running = True
            if state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
                break
            if observed_running and state == lldb.eStateStopped:
                break
            time.sleep(0.05)
        if process.GetState() == lldb.eStateRunning:
            output.write("bounded snapshot interrupt=" + str(process.Stop()) + "\n")
        snapshot(output, "after-execution-window")
    if process.GetState() in (lldb.eStateStopped, lldb.eStateCrashed):
        output.write("detach=" + str(process.Detach()) + "\n")
    output.flush()
