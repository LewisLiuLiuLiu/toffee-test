"""Python model of sar_ctrl.v -- faithful FSM translation for mixed-signal testing.

This is a cycle-accurate translation of the Verilog SAR controller in
toffee_ana/sky130_ef_ip__adc3v_12bit/verilog/sar_ctrl.v.

All sequential register updates happen simultaneously (mirroring the Verilog
posedge-clk behavior) by computing new values first and then assigning.
"""


class SarCtrlDut:
    """Python translation of the SAR controller Verilog FSM.

    SIZE is the ADC resolution in bits. On each call to clock_step(),
    the FSM advances one clock cycle. Digital outputs (data, eoc,
    sample_n, dac_rst) are updated and can be read by PortMapping.
    The comparator result (cmp) is written by MixedSignalSimulator A2D.
    """

    IDLE = 0
    SAMPLE = 1
    RST = 2
    START = 3
    CONV = 4
    DONE = 5

    def __init__(self, size: int = 12):
        self.size = size
        # Inputs (set by external logic / A2D mapping)
        self.cmp = 0
        self.en = 0
        self.soc = 0
        self.swidth = 4
        # Internal registers
        self._state = self.IDLE
        self._result = 0
        self._shift = 0
        self._sample_ctr = 0
        # Outputs (readable by PortMapping via getattr)
        self.eoc = 0
        self.sample_n = 1
        self.dac_rst = 0
        # Individual data bits for D2A mapping
        for i in range(size):
            setattr(self, f"data_{i}", 0)

    @property
    def data(self) -> int:
        return self._result

    def _update_data_pins(self):
        """Sync individual data_N attributes from _result."""
        for i in range(self.size):
            setattr(self, f"data_{i}", (self._result >> i) & 1)

    def clock_step(self):
        """Advance one posedge clk cycle -- mirrors the Verilog always blocks.

        All register updates are computed from the current state and then
        applied simultaneously, matching the Verilog semantics.
        """
        if not self.en:
            return

        mask = (1 << self.size) - 1

        # --- Compute next state (combinational) ---
        nstate = self._state
        if self._state == self.IDLE:
            nstate = self.SAMPLE if self.soc else self.IDLE
        elif self._state == self.SAMPLE:
            nstate = self.RST
        elif self._state == self.RST:
            nstate = self.START if (self.swidth == self._sample_ctr) else self.RST
        elif self._state == self.START:
            nstate = self.CONV
        elif self._state == self.CONV:
            nstate = self.DONE if (self._shift == 1) else self.CONV
        elif self._state == self.DONE:
            nstate = self.IDLE

        # --- Compute new register values (all based on CURRENT state) ---

        # Sample counter
        new_sample_ctr = self._sample_ctr
        if self._state == self.RST:
            if self.swidth == self._sample_ctr:
                new_sample_ctr = 0
            else:
                new_sample_ctr = self._sample_ctr + 1

        # Shift register
        new_shift = self._shift
        if self._state == self.IDLE:
            new_shift = 1 << (self.size - 1)
        elif self._state == self.CONV:
            new_shift = self._shift >> 1

        # SAR logic: current masks out the bit under test if cmp==0
        current = (~self._shift & mask) if (self.cmp == 0) else mask
        next_bit = self._shift >> 1

        new_result = self._result
        if self._state == self.IDLE:
            new_result = 0
        elif self._state == self.RST:
            new_result = 1 << (self.size - 1)
        elif self._state == self.CONV:
            new_result = (self._result | next_bit) & current

        # --- Apply all register updates simultaneously ---
        self._state = nstate
        self._sample_ctr = new_sample_ctr
        self._shift = new_shift
        self._result = new_result

        # --- Update combinational outputs (from NEW state) ---
        self.eoc = 1 if self._state == self.DONE else 0
        self.sample_n = 0 if (self._state == self.SAMPLE or self._state == self.RST) else 1
        self.dac_rst = 1 if (self._state == self.RST or self._state == self.START) else 0
        self._update_data_pins()


def _test_sar_ctrl_basic():
    """Sanity check: run a 4-bit conversion with known comparator responses."""
    dut = SarCtrlDut(size=4)
    dut.en = 1
    dut.soc = 1
    dut.swidth = 0  # minimal sample time

    # Drive through IDLE -> SAMPLE -> RST -> START -> first CONV entry
    # With swidth=0: IDLE(0) → SAMPLE(1) → RST(2) → START(3)
    # After 4 cycles, state = CONV
    for _ in range(4):
        dut.clock_step()
    dut.soc = 0

    assert dut._state == dut.CONV, f"Expected CONV, got {dut._state}"

    # CONV phase: 4 bits. Input = 10 out of 16, so binary 1010
    # cmp=1 means input >= DAC → keep the bit
    # cmp=0 means input < DAC → clear the bit
    expected_cmps = [1, 0, 1, 0]  # MSB first
    for c in expected_cmps:
        dut.cmp = c
        dut.clock_step()

    # Should reach DONE
    assert dut.eoc == 1, f"Expected eoc=1, got {dut.eoc}"
    assert dut.data == 0b1010, f"Expected 0b1010=10, got {dut.data:#06b}={dut.data}"


def _test_sar_ctrl_all_ones():
    """Input at full scale → all bits should be 1."""
    dut = SarCtrlDut(size=4)
    dut.en = 1
    dut.soc = 1
    dut.swidth = 0

    for _ in range(4):
        dut.clock_step()
    dut.soc = 0

    # cmp always 1 → keep every bit
    for _ in range(4):
        dut.cmp = 1
        dut.clock_step()

    assert dut.eoc == 1
    assert dut.data == 0b1111, f"Expected 0b1111, got {dut.data:#06b}"


def _test_sar_ctrl_all_zeros():
    """Input at zero → all bits should be 0."""
    dut = SarCtrlDut(size=4)
    dut.en = 1
    dut.soc = 1
    dut.swidth = 0

    for _ in range(4):
        dut.clock_step()
    dut.soc = 0

    # cmp always 0 → clear every bit
    for _ in range(4):
        dut.cmp = 0
        dut.clock_step()

    assert dut.eoc == 1
    assert dut.data == 0, f"Expected 0, got {dut.data}"


if __name__ == "__main__":
    _test_sar_ctrl_basic()
    _test_sar_ctrl_all_ones()
    _test_sar_ctrl_all_zeros()
    print("PASS: all SAR controller unit tests")
