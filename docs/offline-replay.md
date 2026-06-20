# Offline replay

Backtest replay records bad historical snapshots as replay error entries and increments the replay error counter.

Calibration rejects any trial whose replay summary has replay errors.
