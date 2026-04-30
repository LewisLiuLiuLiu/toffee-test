try:
    from UT_inverter import *
except:
    try:
        from inverter import *
    except:
        from __init__ import *


if __name__ == "__main__":
    dut = DUTinverter()
    # dut.InitClock("clk")

    dut.Step(1)

    dut.Finish()
