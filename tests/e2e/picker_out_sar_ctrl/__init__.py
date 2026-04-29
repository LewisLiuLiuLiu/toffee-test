#coding=utf8

try:
    from . import xspcomm as xsp
except Exception as e:
    import xspcomm as xsp

if __package__ or "." in __name__:
    from .libUT_sar_ctrl import *
else:
    from libUT_sar_ctrl import *


class DUTsar_ctrl(object):

    # initialize
    def __init__(self, *args, **kwargs):
        self.dut = DutUnifiedBase(*args)
        self.xclock = xsp.XClock(self.dut.pxcStep, self.dut.pSelf)
        self.xport  = xsp.XPort()
        self.xclock.Add(self.xport)
        self.event = self.xclock.getEvent()
        self.internal_signals = {}
        self.xcfg = xsp.XSignalCFG(self.dut.GetXSignalCFGPath(), self.dut.GetXSignalCFGBasePtr())
        

        # set output files
        if kwargs.get("waveform_filename"):
            self.dut.SetWaveform(kwargs.get("waveform_filename"))
        if kwargs.get("coverage_filename"):
            self.dut.SetCoverage(kwargs.get("coverage_filename"))

        # All pins
        self.clk = xsp.XPin(xsp.XData(0, xsp.XData.In), self.event)
        self.rst_n = xsp.XPin(xsp.XData(0, xsp.XData.In), self.event)
        self.soc = xsp.XPin(xsp.XData(0, xsp.XData.In), self.event)
        self.cmp = xsp.XPin(xsp.XData(0, xsp.XData.In), self.event)
        self.en = xsp.XPin(xsp.XData(0, xsp.XData.In), self.event)
        self.swidth = xsp.XPin(xsp.XData(4, xsp.XData.In), self.event)
        self.sample_n = xsp.XPin(xsp.XData(0, xsp.XData.Out), self.event)
        self.data = xsp.XPin(xsp.XData(8, xsp.XData.Out), self.event)
        self.eoc = xsp.XPin(xsp.XData(0, xsp.XData.Out), self.event)
        self.dac_rst = xsp.XPin(xsp.XData(0, xsp.XData.Out), self.event)


        # BindDPI or Native pin address
        self.clk.BindDPIPtr(self.dut.GetDPIHandle("clk", 0), self.dut.GetDPIHandle("clk", 1))
        self.rst_n.BindDPIPtr(self.dut.GetDPIHandle("rst_n", 0), self.dut.GetDPIHandle("rst_n", 1))
        self.soc.BindDPIPtr(self.dut.GetDPIHandle("soc", 0), self.dut.GetDPIHandle("soc", 1))
        self.cmp.BindDPIPtr(self.dut.GetDPIHandle("cmp", 0), self.dut.GetDPIHandle("cmp", 1))
        self.en.BindDPIPtr(self.dut.GetDPIHandle("en", 0), self.dut.GetDPIHandle("en", 1))
        self.swidth.BindDPIPtr(self.dut.GetDPIHandle("swidth", 0), self.dut.GetDPIHandle("swidth", 1))
        self.sample_n.BindDPIPtr(self.dut.GetDPIHandle("sample_n", 0), self.dut.GetDPIHandle("sample_n", 1))
        self.data.BindDPIPtr(self.dut.GetDPIHandle("data", 0), self.dut.GetDPIHandle("data", 1))
        self.eoc.BindDPIPtr(self.dut.GetDPIHandle("eoc", 0), self.dut.GetDPIHandle("eoc", 1))
        self.dac_rst.BindDPIPtr(self.dut.GetDPIHandle("dac_rst", 0), self.dut.GetDPIHandle("dac_rst", 1))


        # Add2Port
        self.xport.Add("clk", self.clk.xdata)
        self.xport.Add("rst_n", self.rst_n.xdata)
        self.xport.Add("soc", self.soc.xdata)
        self.xport.Add("cmp", self.cmp.xdata)
        self.xport.Add("en", self.en.xdata)
        self.xport.Add("swidth", self.swidth.xdata)
        self.xport.Add("sample_n", self.sample_n.xdata)
        self.xport.Add("data", self.data.xdata)
        self.xport.Add("eoc", self.eoc.xdata)
        self.xport.Add("dac_rst", self.dac_rst.xdata)


        # Cascaded ports


    def __del__(self):
        self.Finish()

    ################################
    #         User APIs            #
    ################################
    def InitClock(self, name: str):
        self.xclock.Add(self.xport[name])

    def Step(self, i:int = 1):
        self.xclock.Step(i)

    def StepRis(self, callback, args=(), kwargs={}):
        self.xclock.StepRis(callback, args, kwargs)

    def StepFal(self, callback, args=(), kwargs={}):
        self.xclock.StepFal(callback, args, kwargs)

    def ResumeWaveformDump(self):
        return self.dut.ResumeWaveformDump()

    def PauseWaveformDump(self):
        return self.dut.PauseWaveformDump()

    def WaveformPaused(self) -> int:
        """ Returns 1 if waveform export is paused """
        return self.dut.WaveformPaused()

    def GetXPort(self):
        return self.xport

    def GetXClock(self):
        return self.xclock

    def SetWaveform(self, filename: str):
        self.dut.SetWaveform(filename)

    def GetWaveFormat(self) -> str:
        """
        Get the waveform extension, or an empty string if disabled.

        Returns:
            str: The extension of waveform file.
        """
        return self.dut.GetWaveFormat()

    def FlushWaveform(self):
        self.dut.FlushWaveform()

    def SetCoverage(self, filename: str):
        self.dut.SetCoverage(filename)

    def GetCovMetrics(self) -> int:
        """
        Get the bitmask for collected coverage metrics. 0 means coverage is disabled

        Returns:
            int: Collected coverage metrics bitmask:
                - Bit 0: line   (Line coverage)
                - Bit 1: cond   (Condition coverage)
                - Bit 2: fsm    (Finite-State Machine coverage)
                - Bit 3: toggle (Toggle coverage)
                - Bit 4: branch (Branch coverage)
                - Bit 5: assert (Assertion coverage)
        """
        return self.dut.GetCovMetrics()
    
    def CheckPoint(self, name: str) -> int:
        self.dut.CheckPoint(name)

    def Restore(self, name: str) -> int:
        self.dut.Restore(name)

    def GetInternalSignal(self, name: str, index=-1, is_array=False, use_vpi=False):
        if name not in self.internal_signals:
            signal = None
            if self.dut.GetXSignalCFGBasePtr() != 0 and not use_vpi:
                xname = "CFG:" + name
                if is_array:
                    assert index < 0, "Index is not supported for array signal"
                    signal = self.xcfg.NewXDataArray(name, xname)
                elif index >= 0:
                    signal = self.xcfg.NewXData(name, index, xname)
                else:
                    signal = self.xcfg.NewXData(name, xname)
            else:
                assert index < 0, "Index is not supported for VPI signal"
                assert not is_array, "Array is not supported for VPI signal"
                signal = xsp.XData.FromVPI(self.dut.GetVPIHandleObj(name),
                                           self.dut.GetVPIFuncPtr("vpi_get"),
                                           self.dut.GetVPIFuncPtr("vpi_get_value"),
                                           self.dut.GetVPIFuncPtr("vpi_put_value"), "VPI:" + name)
                if use_vpi:
                    assert signal is not None, f"Internal signal {name} not found (Check VPI is enabled)"
            if signal is None:
                return None
            if not isinstance(signal, xsp.XData):
                self.internal_signals[name] = [xsp.XPin(s, self.event) for s in signal]
            else:
                self.internal_signals[name] = xsp.XPin(signal, self.event)
        return self.internal_signals[name]

    def GetInternalSignalList(self, prefix="", deep=99, use_vpi=False):
        if self.dut.GetXSignalCFGBasePtr() != 0 and not use_vpi:
            return self.xcfg.GetSignalNames(prefix)
        else:
            return self.dut.VPIInternalSignalList(prefix, deep)

    def VPIInternalSignalList(self, prefix="", deep=99):
        return self.dut.VPIInternalSignalList(prefix, deep)

    def Finish(self):
        self.dut.Finish()

    def RefreshComb(self):
        self.dut.RefreshComb()

    def AtClone(self):
        """Re-init simulator state in child after fork."""
        return self.dut.atClone()

    ################################
    #      End of User APIs        #
    ################################

    def __getitem__(self, key):
        return xsp.XPin(self.port[key], self.event)

    # Async APIs wrapped from XClock
    async def AStep(self,i: int):
        return await self.xclock.AStep(i)

    async def ACondition(self,fc_cheker):
        return await self.xclock.ACondition(fc_cheker)

    def RunStep(self,i: int):
        return self.xclock.RunStep(i)

    def __setattr__(self, name, value):
        assert not isinstance(getattr(self, name, None),
                              (xsp.XPin, xsp.XData)), \
        f"XPin and XData of DUT are read-only, do you mean to set the value of the signal? please use `{name}.value = ` instead."
        return super().__setattr__(name, value)


if __name__=="__main__":
    dut=DUTsar_ctrl()
    dut.Step(100)
