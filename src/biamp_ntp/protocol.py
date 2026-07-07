"""Biamp NTP attribute codes, grouped by block type.

These are the attribute names used in GET/SET commands. Which set applies
depends on the blocks in your running design; discover their instance IDs with
:func:`biamp_ntp.scan.scan`. This is a convenience map of the common ones, not
an exhaustive list -- any attribute string works with ``BiampNTP.get``/``set``.

Levels are in dB unless noted; mute/invert are 0/1; index is the channel /
crosspoint selector for that block.
"""

# --- Nexia PM input block ---------------------------------------------------
INPUT_LEVEL_PM = "INPLVLPML"     # idx = input
INPUT_MUTE_PM = "INPMUTEPML"     # idx = input
INPUT_GAIN_PM = "INPGAINPML"     # idx = input (analog input gain)

# --- Nexia PM output block --------------------------------------------------
OUTPUT_LEVEL_PM = "OUTLVLPM"     # idx = output channel, -100..+12 dB
OUTPUT_MUTE_PM = "OUTMUTEPM"     # idx = output channel, 0/1
OUTPUT_INVERT_PM = "OUTINVRTPM"  # idx = output channel, 0/1 (polarity)
OUTPUT_FS_PM = "OUTFSPM"         # idx = output channel (full-scale / range)

# --- Generic (non-PM) output block ------------------------------------------
OUTPUT_LEVEL = "OUTLVL"          # idx = output channel
OUTPUT_MUTE = "OUTMUTE"          # idx = output channel

# --- Standard matrix mixer --------------------------------------------------
MATRIX_IN_LEVEL = "MMLVLIN"      # idx = input
MATRIX_OUT_LEVEL = "MMLVLOUT"    # idx = output, -100..+12 dB
MATRIX_OUT_MUTE = "MMMUTEOUT"    # idx = output, 0/1
MATRIX_XP_LEVEL = "MMLVLXP"      # idx1 = input row, idx2 = output col, -100..0 dB
MATRIX_XP_MUTE = "MMMUTEXP"      # idx1 = input row, idx2 = output col, 0/1

# --- Standard level (fader) block -------------------------------------------
FADER_LEVEL = "FDRLVL"           # idx = channel
FADER_MUTE = "FDRMUTE"           # idx = channel

# --- Device -----------------------------------------------------------------
DEVICE_ID = "DEVID"              # GET 0 DEVID -> device number
PRESET = "PRESET"                # RECALL 0 PRESET <n> (system-wide; see BiampNTP.recall_preset)
