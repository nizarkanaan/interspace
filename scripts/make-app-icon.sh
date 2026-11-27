#!/bin/sh
# Rebuilds app/macos/AppIcon.icns from scripts/make-app-icon.swift (every size macOS asks for, 16 to 1024).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
swift "$root/scripts/make-app-icon.swift" "$work/icon-1024.png" >/dev/null
set_dir="$work/AppIcon.iconset"
mkdir "$set_dir"
for s in 16 32 128 256 512; do
  sips -z $s $s "$work/icon-1024.png" --out "$set_dir/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d "$work/icon-1024.png" --out "$set_dir/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$set_dir" -o "$root/app/macos/AppIcon.icns"
echo "$root/app/macos/AppIcon.icns"
