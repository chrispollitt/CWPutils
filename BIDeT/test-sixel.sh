#!/usr/bin/env bash

# Requirements: just ImageMagick (and a Sixel terminal, of course)
# B9 November 2023

## INIT ###########################
# The following defaults may be overridden if autodetection succeeds.
numcolors=16     # Default number of colors in the palette.
background=white # Default montage background.
foreground=black # Default text color.
width=800	       # Default width of screen in pixels.
timeout=0.25		 # How long to wait for terminal to respond to a control sequence (in seconds).

# Save the original file descriptors
exec 3<&0 4<&1 5<&2
# Reassign STDIN and STDOUT to /dev/tty
exec </dev/tty >/dev/tty 2>&1

# Sanity checks and compatibility
if ! command -v montage >/dev/null; then
  echo "Please install ImageMagick" >&2
  EXIT_CODE=1
  exit 1
fi

shopt -s expand_aliases		# Allow aliases for working around quirks.

if command -v gsed >/dev/null; then
  alias sed=gsed		# Use GNU sed for MacOS & BSD.
fi

if [[ "$COMSPEC" ]]; then
  alias convert="magick convert" # Shun MS Windows' "convert" command.
fi

## CLEANUP ########################
export EXIT_CODE=0    
cleanup() {
  echo -n $'\e\\'		   # Escape sequence to stop SIXEL.
	if [[ -t 1 ]]; then  #
    stty echo			     # Reset terminal to show characters.
	fi
  exit $EXIT_CODE 
}
trap cleanup SIGINT SIGHUP SIGABRT EXIT
## LOOK_FOR_SIXEL_TERM #############
look_for_sixel_term() {
  local gterm="mlterm xterm"
  local nterm=""
  local uname=$(uname -s | tr '[:upper:]' '[:lower:]')  # Convert uname output to lowercase
  local loc

  # Determine terminal for specific OS (case-insensitive matching)
  case $uname in
    cygwin*|msys*|mingw*)
      nterm="mintty"
      ;;
    darwin)
      nterm="iTerm"
      ;;
    *linux|*bsd|sunos|solaris)
      ;;  # No specific terminal to add for these platforms
    *)
      echo "Unsupported operating system: $uname"
      return 1
      ;;
  esac

  # Special case for macOS (Darwin) to check for nterm in Applications folders
  if [[ $uname == "darwin" ]]; then
    loc=$(ls -1d /Applications/$nterm.app /Users/$USER/Applications/$nterm.app 2>/dev/null | head -1)
    if [[ -n $loc ]]; then
      echo "Good news: you have $nterm at $loc"
      return 0
    fi
  fi

  # Look for terminals gterm and nterm in the PATH
  for term in $nterm $gterm; do
    loc=$(type -p $term 2>/dev/null)
    if [[ -n $loc && -x $loc ]]; then
      echo "Good news: you have $term at $loc"
			if [[ $term == xterm ]]; then
			  echo "Run it like this: xterm -ti vt340"
			fi
      return 0
    fi
  done

  # If no terminal was found
  echo "No suitable sixel-compatible terminal found."
  return 1
}
## AUTODETECT ######################
autodetect() {
  # Various terminal automatic configuration routines.
  # Don't show escape sequences the terminal doesn't understand.
	if [[ -t 1 ]]; then
    stty -echo			
	fi
  # IS TERMINAL SIXEL CAPABLE?		# Send Device Attributes
  IFS=";?c" read -a REPLY -s -t 1 -d "c" -p $'\e[c' >&2
  for code in "${REPLY[@]}"; do
    if [[ $code == "4" ]]; then
      hassixel=yup
      break
    fi
  done
  # YAFT is vt102 compatible, cannot respond to vt220 escape sequence.
  if [[ "$TERM" == yaft* ]]; then hassixel=yeah; fi
  if [[ -z "$hassixel" && -z "$LSIX_FORCE_SIXEL_SUPPORT" ]]; then
    cat <<-EOF >&2
Error: Your terminal does not report having sixel graphics support.
EOF
#    read -s -t 1 -d "c" -p $'\e[c' >&2
#    if [[ "$REPLY" ]]; then
#      echo
#      cat -v <<< "Please mention device attribute codes: ${REPLY}c"
#    fi
    look_for_sixel_term
    EXIT_CODE=1
    exit 1
  fi
  # SIXEL SCROLLING (~DECSDM) is now presumed to be enabled.
  # See https://github.com/hackerb9/lsix/issues/41 for details.
  # TERMINAL COLOR AUTODETECTION.
  # Find out how many color registers the terminal has
  IFS=";"  read -a REPLY -s -t ${timeout} -d "S" -p $'\e[?1;1;0S' >&2
  [[ ${REPLY[1]} == "0" ]] && numcolors=${REPLY[2]}
  # YAFT is vt102 compatible, cannot respond to vt220 escape sequence.
  if [[ "$TERM" == yaft* ]]; then numcolors=256; fi
  # Increase colors, if needed
  if [[ $numcolors -lt 256 ]]; then
    # Attempt to set the number of colors to 256.
    # This will work for xterm, but fail on a real vt340.
    IFS=";"  read -a REPLY -s -t ${timeout} -d "S" -p $'\e[?1;3;256S' >&2
    [[ ${REPLY[1]} == "0" ]] && numcolors=${REPLY[2]}
  fi
  # Query the terminal background and foreground colors.
  IFS=";:/"  read -a REPLY -r -s -t ${timeout} -d "\\" -p $'\e]11;?\e\\' >&2
  if [[ ${REPLY[1]} =~ ^rgb ]]; then
    # Return value format: $'\e]11;rgb:ffff/0000/ffff\e\\'.
    # ImageMagick wants colors formatted as #ffff0000ffff.
    background='#'${REPLY[2]}${REPLY[3]}${REPLY[4]%%$'\e'*}
    IFS=";:/"  read -a REPLY -r -s -t ${timeout} -d "\\" -p $'\e]10;?\e\\' >&2
    if [[ ${REPLY[1]} =~ ^rgb ]]; then
      foreground='#'${REPLY[2]}${REPLY[3]}${REPLY[4]%%$'\e'*}
      # Check for "Reverse Video" (DECSCNM screen mode).
      IFS=";?$"  read -a REPLY -s -t ${timeout} -d "y" -p $'\e[?5$p'
      if [[ ${REPLY[2]} == 1 || ${REPLY[2]} == 3 ]]; then
        temp=$foreground
        foreground=$background
        background=$temp
      fi
    fi
  fi
  # YAFT is vt102 compatible, cannot respond to vt220 escape sequence.
  if [[ "$TERM" == yaft* ]]; then background=black; foreground=white; fi
  # Send control sequence to query the sixel graphics geometry to
  # find out how large of a sixel image can be shown.
  IFS=";"  read -a REPLY -s -t ${timeout} -d "S" -p $'\e[?2;1;0S' >&2
  if [[ ${REPLY[2]} -gt 0 ]]; then
    width=${REPLY[2]}
  else
    # Nope. Fall back to dtterm WindowOps to approximate sixel geometry.
    IFS=";" read -a REPLY -s -t ${timeout} -d "t" -p $'\e[14t' >&2
    if [[ $? == 0  &&  ${REPLY[2]} -gt 0 ]]; then
      width=${REPLY[2]}
    fi
  fi
  # BUG WORKAROUND: XTerm cannot show images wider than 1000px.
  # Remove this hack once XTerm gets fixed. Last checked: XTerm(344)
  if [[ $TERM =~ xterm && $width -ge 1000 ]]; then  width=1000; fi
  # Space on either side of each tile is less than 0.5% of total screen width
  tilexspace=$((width/201))
  tileyspace=$((tilexspace/2))
  # Figure out how many tiles we can fit per row. ("+ 1" is for -shadow).
  numtiles=$((width/(tilewidth + 2*tilexspace + 1)))

  # cleanup
	echo -n $'\e\\'		# Escape sequence to stop SIXEL.
	if [[ -t 1 ]]; then 
    stty echo			    # Reset terminal to show characters.
	fi
	trap - SIGINT SIGHUP SIGABRT EXIT
  # Restore the original file descriptors
  exec <&3 >&4 2>&5
	exec 3<&- 4<&- 5<&-
	# output result
  echo "Sixel support found. fg=$foreground bg=$background nc=$numcolors"
}
## MAIN ##########################
# Discover and setup the terminal
autodetect
