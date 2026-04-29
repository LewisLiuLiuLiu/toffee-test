try:
    from UT_sar_ctrl import *
except:
    try:
        from sar_ctrl import *
    except:
        from __init__ import *


if __name__ == "__main__":
    dut = DUTsar_ctrl()
    # dut.InitClock("clk")

    dut.Step(1)

    dut.Finish()
