#!/usr/bin/env python3
"""Print 1DTE put OTM probability report."""
from otm_probability import format_report, generate_report

if __name__ == "__main__":
    print("Fetching SPY + VIX data...")
    report = generate_report(dte=1, strike_range=15, min_p_otm=0.85)
    print(format_report(report))
