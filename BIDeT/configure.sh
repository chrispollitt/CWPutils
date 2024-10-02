#!/bin/bash

# Function to check if a command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Check for modern Bash
check_bash() {
  if command_exists bash; then
    echo "Bash is installed."
  else
    echo "Error: Bash is not installed."
    return 1
  fi
	if (( ${BASH_VERSINFO[0]} < 4 )); then
    echo "Error: Bash is too old."
    return 1
	fi
}

# Check for Perl
check_perl() {
  if command_exists perl; then
    echo "Perl is installed."
  else
    echo "Error: Perl is not installed."
    return 1
  fi
}

# Check for Ghostscript and its fonts
check_ghostscript() {
  if command_exists gs; then
    echo "GhostScript is installed."
    if gs -h | grep -q "fonts"; then
      echo "GhostScript fonts are available."
    else
      echo "Warning: GhostScript fonts may not be installed."
    fi
  else
    echo "Error: GhostScript is not installed."
    return 1
  fi
	# collect install font list
	echo "Collecting list of fonts..."
	for f in `fc-list|cut -d: -f1`;do (fc-query $f|perl -lne '/postscriptname: "(.+?)"/ and print $1');done|sort -fu > fontlist.txt
}

# Check for Netpbm and pnmrotate
check_netpbm() {
  if command_exists pnmrotate; then
    echo "Netpbm (pnmrotate) is installed."
  else
    echo "Error: Netpbm or pnmrotate is not installed."
    return 1
  fi
}

# Check for MoreUtils (for sponge)
check_moreutils() {
  if command_exists sponge; then
    echo "MoreUtils (sponge) is installed."
  else
    echo "Error: MoreUtils (sponge) is not installed."
    return 1
  fi
}

# Check for libSixel (with libpng support)
check_libsixel() {
  if command_exists img2sixel; then
    echo "img2sixel is installed."
    # Check if img2sixel has libpng support by looking for 'libpng' in its version information
    if img2sixel --version 2>&1 | grep -q "libpng"; then
      echo "img2sixel has libpng support."
    else
      echo "Warning: img2sixel does not appear to have libpng support."
    fi
  else
    echo "Error: img2sixel (from libSixel) is not installed."
    return 1
  fi
}

# Check for ImageMagick
check_imagemagick() {
  if command_exists convert; then
    echo "ImageMagick is installed."
  else
    echo "Error: ImageMagick is not installed."
    return 1
  fi
}

# Main function to run all checks
run_checks() {
  echo "Checking for required dependencies..."
  check_bash || exit 1
  check_perl || exit 1
  check_ghostscript || exit 1
  check_netpbm || exit 1
  check_moreutils || exit 1
  check_libsixel || exit 1
  check_imagemagick || exit 1
  echo "All required dependencies are installed."
}

# Run the checks
run_checks
bash ./test-sixel.sh