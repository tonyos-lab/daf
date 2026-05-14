#!/usr/bin/env python3
"""Quick cost report for R&D budget tracking."""
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="DAF cost report")
    parser.add_argument("--period", choices=["today", "week", "month"], default="today")
    args = parser.parse_args()
    print(f"Cost report for period: {args.period}")
    print("(Connect to experiment database to see actual costs)")

if __name__ == "__main__":
    main()
