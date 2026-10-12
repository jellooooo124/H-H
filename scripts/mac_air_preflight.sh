#!/usr/bin/env bash
# Run locally on Mac; does not install or change anything.
set -u
printf 'Mac OS: '; sw_vers -productVersion 2>/dev/null || echo unknown
printf 'Model: '; sysctl -n hw.model 2>/dev/null || echo unknown
printf 'Architecture: '; uname -m
printf 'RAM (GiB): '; RAM=$(sysctl -n hw.memsize 2>/dev/null || echo 0); awk "BEGIN {printf \"%.1f\\n\", $RAM/1073741824}"
printf 'Free disk:\n'; df -h "$HOME" | tail -1
for tool in python3 node npm docker ssh; do
  if command -v "$tool" >/dev/null; then printf '%-8s %s\n' "$tool" "$(command -v "$tool")"; else printf '%-8s NOT INSTALLED\n' "$tool";fi
done
printf '\nNo packages installed and no network or patient data accessed.\n'
