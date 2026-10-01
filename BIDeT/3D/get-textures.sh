#!/usr/bin/env bash
# Fetch the Word textures used by four presets from arizzitano/css3wordart.
# That repo has no license file, so they are deliberately not bundled:
# running this is your decision.  Each is a 128x128 PNG of a few KB.
set -e
cd "$(dirname "$0")"
mkdir -p textures
base=https://raw.githubusercontent.com/arizzitano/css3wordart/master/less/textures
for t in GreenMarble PaperBag Granite; do
  echo "fetching Texture-$t.png"
  curl -fsSL -o "textures/Texture-$t.png" "$base/Texture-$t.png"
done
echo done
