#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIDeT - Use this after you're done with Toilet!
Why did I write this? Because I DEcided To. :)
"""

import argparse
import os
import sys
import random
import tempfile
import subprocess
import textwrap
import shutil
import re
from pathlib import Path

class PostScriptSimple:
    """Python version of PostScript::Simple"""
    
    # Define standard ISO fonts
    isofonts = [
        "Courier", "Courier-Bold", "Courier-BoldOblique", "Courier-Oblique",
        "Helvetica", "Helvetica-Bold", "Helvetica-BoldOblique", "Helvetica-Oblique",
        "Symbol", "Times-Bold", "Times-BoldItalic", "Times-Italic", "Times-Roman"
    ]
    
    # Load extended fonts list
    try:
        with open('/usr/local/share/BIDeT/fontlist.txt', 'r') as f:
            extfonts = [line.strip() for line in f]
    except FileNotFoundError:
        extfonts = []
    
    # Color definitions (dictionary mapping color names to RGB values)
    pscolours = {
        # Original colours from PostScript::Simple
        "brightred": [255, 0, 0], "brightgreen": [0, 255, 0], "brightblue": [0, 0, 255],
        "red": [204, 0, 0], "green": [0, 204, 0], "blue": [0, 0, 204],
        "darkred": [127, 0, 0], "darkgreen": [0, 127, 0], "darkblue": [0, 0, 127],
        "grey10": [25, 25, 25], "grey20": [51, 51, 51], "grey30": [76, 76, 76],
        "grey40": [102, 102, 102], "grey50": [127, 127, 127], "grey60": [153, 153, 153],
        "grey70": [178, 178, 178], "grey80": [204, 204, 204], "grey90": [229, 229, 229],
        "black": [0, 0, 0], "white": [255, 255, 255],
        
        # X-Windows colours - shortened list for performance
        "aliceblue": [240, 248, 255], "antiquewhite": [250, 235, 215], "aqua": [0, 255, 255],
        "aquamarine": [127, 255, 212], "azure": [240, 255, 255], "beige": [245, 245, 220],
        "bisque": [255, 228, 196], "blanchedalmond": [255, 255, 205], "blueviolet": [138, 43, 226],
        "brown": [165, 42, 42], "burlywood": [222, 184, 135], "cadetblue": [95, 158, 160],
        "cornflowerblue": [100, 149, 237], "cyan": [0, 255, 255],
        "gold": [255, 215, 0], "gray": [128, 128, 128], "grey": [128, 128, 128],
        "magenta": [255, 0, 255], "orange": [255, 165, 0], "purple": [128, 0, 128],
        "silver": [192, 192, 192], "snow": [255, 250, 250], "yellow": [255, 255, 0],
    }
    
    # Paper size definitions
    pspaper = {
        "A0": [2384, 3370],
        "A1": [1684, 2384],
        "A2": [1191, 1684],
        "A3": [841.88976, 1190.5512],
        "A4": [595.27559, 841.88976],
        "A5": [420.94488, 595.27559],
        "A6": [297, 420],
        "A7": [210, 297],
        "A8": [148, 210],
        "A9": [105, 148],
    }
    
    def __init__(self, papersize="A4", colour=True, eps=False, units="in", reencode="ISOLatin1Encoding"):
        self.papersize = papersize
        self.colour = colour
        self.eps = eps
        self.units = units
        self.reencode = reencode
        self.content = []
        
        # Initialize page tracking
        self.current_fontsize = 0
        self.page_count = 0
        self.current_page = []
        
        # Get paper dimensions
        if papersize in self.pspaper:
            self.width, self.height = self.pspaper[papersize]
        else:
            self.width, self.height = 595, 842  # Default A4 size
    
    def _add_ps_header(self):
        """Add the basic PostScript header"""
        self.content.append("%!PS-Adobe-3.0")
        if self.eps:
            self.content.append(" EPSF-1.2")
        self.content.append("")
        
        # Add document metadata
        self.content.append("%%Title: (Python PostScript::Simple)")
        self.content.append("%%LanguageLevel: 1")
        self.content.append("%%Creator: Python PostScript::Simple")
        self.content.append(f"%%BoundingBox: 0 0 {self.width} {self.height}")
        
        # Add paper size info
        if self.papersize in self.pspaper:
            self.content.append(f"%%DocumentMedia: {self.papersize} {self.width} {self.height} 0 ( ) ( )")
        
        self.content.append("%%EndComments")
        
        # Prolog section
        self.content.append("%%BeginProlog")
        self.content.append("/ll 1 def systemdict /languagelevel known {")
        self.content.append("/ll languagelevel def } if")
        
        # Add basic definitions
        self._add_basic_definitions()
        
        # Font encoding if needed
        if self.reencode:
            self._add_font_encoding()
            
        self.content.append("%%EndProlog")
        
        # Setup section
        self.content.append("%%BeginSetup")
        self.content.append("%%EndSetup")
    
    def _add_basic_definitions(self):
        """Add basic PostScript definitions"""
        self.content.append("""
/box {
  newpath 3 copy pop exch 4 copy pop pop
  8 copy pop pop pop pop exch pop exch
  3 copy pop pop exch moveto lineto
  lineto lineto pop pop pop pop closepath
} bind def

/circle {newpath 0 360 arc closepath} bind def
""")
    
    def _add_font_encoding(self):
        """Add font encoding setup to the document"""
        self.content.append("""
/STARTDIFFENC { mark } bind def
/ENDDIFFENC { 
    counttomark 2 add -1 roll 256 array copy
    /TempEncode exch def
    /EncodePointer 0 def
    {
        counttomark -1 roll
        dup type dup /marktype eq {
            pop pop exit
        } {
            /nametype eq {
                TempEncode EncodePointer 3 -1 roll put
                /EncodePointer EncodePointer 1 add def
            } {
                /EncodePointer exch def
            } ifelse
        } ifelse
    } loop
    TempEncode def
} bind def

/ISOLatin1Encoding where {
    pop
} {
    /ISOLatin1Encoding StandardEncoding STARTDIFFENC
        144 /dotlessi /grave /acute /circumflex /tilde 
        /macron /breve /dotaccent /dieresis /.notdef /ring 
        /cedilla /.notdef /hungarumlaut /ogonek /caron /space 
        /exclamdown /cent /sterling /currency /yen /brokenbar 
        /section /dieresis /copyright /ordfeminine 
        /guillemotleft /logicalnot /hyphen /registered 
        /macron /degree /plusminus /twosuperior 
        /threesuperior /acute /mu /paragraph /periodcentered 
        /cedilla /onesuperior /ordmasculine /guillemotright 
        /onequarter /onehalf /threequarters /questiondown 
        /Agrave /Aacute /Acircumflex /Atilde /Adieresis 
        /Aring /AE /Ccedilla /Egrave /Eacute /Ecircumflex 
        /Edieresis /Igrave /Iacute /Icircumflex /Idieresis 
        /Eth /Ntilde /Ograve /Oacute /Ocircumflex /Otilde 
        /Odieresis /multiply /Oslash /Ugrave /Uacute 
        /Ucircumflex /Udieresis /Yacute /Thorn /germandbls 
        /agrave /aacute /acircumflex /atilde /adieresis 
        /aring /ae /ccedilla /egrave /eacute /ecircumflex 
        /edieresis /igrave /iacute /icircumflex /idieresis 
        /eth /ntilde /ograve /oacute /ocircumflex /otilde 
        /odieresis /divide /oslash /ugrave /uacute 
        /ucircumflex /udieresis /yacute /thorn /ydieresis
    ENDDIFFENC
} ifelse

/REENCODEFONT { % /Newfont NewEncoding /Oldfont
    findfont dup length 4 add dict
    begin
        { % forall
            1 index /FID ne 
            2 index /UniqueID ne and
            2 index /XUID ne and
            { def } { pop pop } ifelse
        } forall
        /Encoding exch def
        /BitmapWidths false def
        /ExactSize 0 def
        /InBetweenSize 0 def
        /TransformedChar 0 def
        currentdict
    end
    definefont pop
} bind def
""")
        # Re-encode the ISO fonts
        for font in self.isofonts:
            self.content.append(f"/{font}-iso {self.reencode} /{font} REENCODEFONT")
    
    def newpage(self):
        """Create a new page in the document"""
        if self.eps:
            print("Warning: Do not use newpage for EPS files", file=sys.stderr)
            return
            
        # Close previous page if exists
        if self.current_page:
            self.content.extend(self.current_page)
            self.content.append("showpage")
        
        # Increment page count
        self.page_count += 1
        
        # Start new page
        self.current_page = []
        self.current_page.append(f"%%Page: {self.page_count} {self.page_count}")
        self.current_page.append("%%BeginPageSetup")
        self.current_page.append("/pagelevel save def")
        self.current_page.append("%%EndPageSetup")
    
    def setcolour(self, *args):
        """Set the drawing color
        
        Args:
            Either a color name as string or r,g,b values (0-255)
        """
        if len(args) == 1:
            # Color name provided
            color_name = args[0].lower()
            if color_name in self.pscolours:
                r, g, b = self.pscolours[color_name]
            else:
                print(f"Error: Bad colour name '{color_name}'", file=sys.stderr)
                return
        elif len(args) == 3:
            # RGB values provided
            r, g, b = args
        else:
            print(f"Error: Invalid arguments to setcolour", file=sys.stderr)
            return
            
        # Convert to PostScript range (0-1)
        r = round(r / 255, 5)
        g = round(g / 255, 5)
        b = round(b / 255, 5)
        
        if self.colour:
            self.current_page.append(f"{r} {g} {b} setrgbcolor")
        else:
            # Convert to grayscale (better conversion than average)
            gray = round(0.3*r + 0.59*g + 0.11*b, 5)
            self.current_page.append(f"{gray} setgray")
    
    def setfont(self, font_name, size):
        """Set the current font and size
        
        Args:
            font_name: Name of the PostScript font
            size: Font size in points
        """
        self.current_page.append(f"/{font_name} findfont {size} scalefont setfont")
        self.current_fontsize = size
    
    def text(self, x, y, text_string, align="left", rotate=0):
        """Add text to the document
        
        Args:
            x, y: Coordinates
            text_string: The text to display
            align: Text alignment ("left", "center", "right")
            rotate: Rotation angle in degrees
        """
        # Escape special characters in PostScript
        text_string = text_string.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        
        # Start a new path and move to position
        self.current_page.append("newpath")
        self.current_page.append(f"{x} {y} moveto")
        
        # Handle rotation
        if rotate != 0:
            self.current_page.append(f"{rotate} rotate")
        
        # Handle alignment
        if align == "left":
            self.current_page.append(f"({text_string}) show")
        elif align == "center" or align == "centre":
            self.current_page.append(f"({text_string}) dup stringwidth pop 2 div neg 0 rmoveto show")
        elif align == "right":
            self.current_page.append(f"({text_string}) dup stringwidth pop neg 0 rmoveto show")
            
        # Restore rotation if needed
        if rotate != 0:
            self.current_page.append(f"{-rotate} rotate")
    
    def output(self, filename):
        """Write the PostScript content to a file
        
        Args:
            filename: Output filename
        """
        # Add header if not done already
        if not self.content or not self.content[0].startswith("%!PS"):
            self._add_ps_header()
            
        # Add current page content if any
        if self.current_page:
            self.content.extend(self.current_page)
            if not self.eps:
                self.content.append("pagelevel restore")
                self.content.append("showpage")
        
        # Add trailer and EOF
        self.content.append("%%Trailer")
        self.content.append("%%EOF")
        
        with open(filename, 'w', encoding='latin1') as f:
            for line in self.content:
                f.write(f"{line}\n")


class BIDeT:
    """BIDeT - Use this after you're done with Toilet!"""
    
    def __init__(self):
        self.debug = False
        self.temp_dir = None
        self.temp_prefix = None
    
    def test_sixel(self):
        """Test if the terminal supports Sixel"""
        try:
            # Mock response for testing if command not available
            if not shutil.which("test-sixel"):
                return "black", "white"
                
            result = subprocess.run(["test-sixel"], capture_output=True, text=True)
            output = result.stdout.strip()
            
            match = re.search(r'Sixel support found. fg=(\S+) bg=(\S+) nc=(\S+)', output)
            if match:
                return match.group(1), match.group(2)
            else:
                return "black", "white"
        except:
            return "black", "white"
    
    def collapse_or_find_font(self, mode, font, available_fonts):
        """Collapse font names or find a matching font"""
        try:
            with open('/usr/local/share/BIDeT/fontsuffixlist.txt', 'r') as f:
                types = [line.strip() for line in f]
        except FileNotFoundError:
            types = []
            
        # Sort by length
        types.sort(key=len, reverse=True)
        
        if mode == "collapse":
            # Collapse fonts mode
            seen = set()
            collapsed_fonts = []
            
            for font_name in available_fonts:
                # Remove specified suffixes
                for suffix in types:
                    if font_name.endswith(suffix) or font_name.endswith('-' + suffix):
                        font_name = font_name[:-len(suffix)]
                        if font_name.endswith('-'):
                            font_name = font_name[:-1]
                        break
                
                # Add base font to collapsed list if not seen
                if font_name not in seen:
                    collapsed_fonts.append(font_name)
                    seen.add(font_name)
                    
            return collapsed_fonts
            
        elif mode == "search":
            # Find closest font mode
            for suffix in reversed(types):
                # Try without dash
                candidate = font + suffix
                if candidate in available_fonts:
                    if self.debug:
                        print(f"Debug: font={candidate}", file=sys.stderr)
                    return candidate
                
                # Try with dash
                candidate = font + '-' + suffix
                if candidate in available_fonts:
                    if self.debug:
                        print(f"Debug: font={candidate}", file=sys.stderr)
                    return candidate
                    
            return None
    
    def test_font(self, font, iso):
        """Test if font is valid and potentially list available fonts"""
        isofonts = PostScriptSimple.isofonts
        fonts = PostScriptSimple.extfonts
        
        # List fonts
        if font == "list":
            print("--- Regular ---")
            collapsed = self.collapse_or_find_font("collapse", "", fonts)
            for f in sorted(collapsed):
                print(f)
                
            print("--- Latin1 compatible ---")
            iso_collapsed = self.collapse_or_find_font("collapse", "", isofonts)
            for f in sorted(iso_collapsed):
                print(f)
            sys.exit(0)
        
        # Random font
        if font == "random":
            if iso:
                font = random.choice(isofonts)
            else:
                font = random.choice(fonts)
        
        # Check if font is valid
        if iso:
            if font not in isofonts:
                closest_font = self.collapse_or_find_font("search", font, isofonts)
                if closest_font:
                    font = closest_font
                else:
                    print(f"Error: Invalid ISO font: {font}", file=sys.stderr)
                    sys.exit(1)
            font += "-iso"
        else:
            if font not in fonts and font not in isofonts:
                closest_font = self.collapse_or_find_font("search", font, fonts + isofonts)
                if closest_font:
                    font = closest_font
                else:
                    print(f"Error: Invalid font: {font}", file=sys.stderr)
                    sys.exit(1)
        
        return font
    
    def test_colours(self, colour, background):
        """Test if colors are valid and potentially list available colors"""
        colour = colour.lower()
        background = background.lower()
        
        # Get colour lists
        colours = list(PostScriptSimple.pscolours.keys())
        backgrounds = colours
        
        # List colors
        if colour == "list" or background == "list":
            for c in sorted(colours):
                print(c)
            sys.exit(0)
        
        # Random colors
        if colour == "random":
            colour = random.choice(colours)
        if background == "random":
            background = random.choice(backgrounds)
        
        # Check colour
        if colour != 'default' and colour not in colours:
            print(f"Error: Invalid colour: {colour}", file=sys.stderr)
            sys.exit(1)
        
        # Check background
        if background != 'transparent' and background not in backgrounds:
            print(f"Error: Invalid background: {background}", file=sys.stderr)
            sys.exit(1)
        
        # Make sure not same
        if colour == background and colour != 'default' and background != 'transparent':
            print(f"Error: colour and background cannot be the same", file=sys.stderr)
            sys.exit(1)
        
        return colour, background
    
    def hex48_to_rgb(self, hex_str):
        """Convert 48-bit hex color to RGB values"""
        # Remove leading # if present
        hex_str = hex_str.lstrip('#')
        
        # Extract components (4 hex digits each)
        r = int(hex_str[0:4], 16)
        g = int(hex_str[4:8], 16)
        b = int(hex_str[8:12], 16)
        
        # Scale to 8-bit
        r = int(r / 257)
        g = int(g / 257)
        b = int(b / 257)
        
        return r, g, b
    
    def run_prog(self, cmd):
        """Run a command and check for errors"""
        if self.debug:
            print(f"CMD={cmd}", file=sys.stderr)
        
        # Run command directly without redirecting to log file
        result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE)
        
        if result.returncode != 0:
            print(f"Error: System call failed: {cmd}", file=sys.stderr)
            print(result.stderr.decode(), file=sys.stderr)
            sys.exit(1)
    
    def main(self):
        """Main function"""
        parser = argparse.ArgumentParser(description='BIDeT - Use this after you\'re done with Toilet!')
        parser.add_argument('-a', '--ansi', action='store_true', help='Use ANSI instead of SIXEL')
        parser.add_argument('-b', '--background', default='transparent', help='Set background color')
        parser.add_argument('-c', '--colour', default='default', help='Set text color')
        parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode')
        parser.add_argument('-f', '--font', default='Helvetica', help='Set font face')
        parser.add_argument('-l', '--line', type=float, default=1, help='Set line spacing')
        parser.add_argument('-p', '--preserve', action='store_true', help='Preserve newlines')
        parser.add_argument('-r', '--rotate', action='store_true', help='Rotate right by 90 degrees')
        parser.add_argument('-s', '--size', type=int, default=65, help='Set font size')
        parser.add_argument('-w', '--width', type=int, default=20, help='Set width')
        parser.add_argument('-v', '--version', action='store_true', help='Show version')
        parser.add_argument('text', nargs='*', help='Text to display or filename')
        
        args = parser.parse_args()
        
        # Set up debug mode
        self.debug = args.debug
        
        # Show version
        if args.version:
            print("Version: 1.3")
            sys.exit(0)
        
        # Create temp directory for files
        if os.path.exists("/dev/shm"):
            # Use /dev/shm for better performance on Linux
            shm_path = f"/dev/shm/{os.environ.get('USER', 'bidet')}"
            os.makedirs(shm_path, exist_ok=True)
            self.temp_prefix = os.path.join(shm_path, "bidet_tmp")
        else:
            # Fallback to regular temp directory
            self.temp_dir = tempfile.mkdtemp(prefix="bidet_")
            self.temp_prefix = os.path.join(self.temp_dir, "bidet_tmp")
        
        # Check for terminal Sixel support
        term_foreground, term_background = self.test_sixel()
        
        # Font testing
        if args.font == "list":
            self.test_font(args.font, False)
        
        # Color testing
        if args.colour == "list" or args.background == "list":
            self.test_colours(args.colour, args.background)
        
        # Get input text
        text_lines = []
        
        if not args.text:
            # No arguments, read from stdin
            text_lines = sys.stdin.readlines()
        elif args.text[0] == '-':
            # Dash argument, read from stdin
            text_lines = sys.stdin.readlines()
        elif len(args.text) == 1 and os.path.isfile(args.text[0]):
            # Single argument is a file
            with open(args.text[0], 'r', encoding='utf-8') as f:
                text_lines = f.readlines()
        else:
            # Arguments are direct text
            text_lines = args.text
        
        # Process text according to preserve flag
        if not args.preserve:
            # Join all lines with spaces and rewrap
            text = ' '.join(line.strip() for line in text_lines)
            wrapped_text = textwrap.fill(text, args.width)
            text_lines = wrapped_text.split('\n')
        
        # Check if text contains Latin1 characters
        iso = any(ord(c) > 127 for line in text_lines for c in line)
        
        # Validate font
        font = self.test_font(args.font, iso)
        
        # Validate colors
        colour, background = self.test_colours(args.colour, args.background)
        if colour == 'default':
            colour = term_foreground
        if background == 'transparent':
            background = term_background
        
        # Create PostScript file
        ps = PostScriptSimple(
            papersize="A0",
            colour=True,
            eps=False,
            units="in",
            reencode="ISOLatin1Encoding"
        )
        
        ps.newpage()
        
        # Handle color setting
        if colour.lower() == 'white':
            # Can't use true white due to masking
            colour = "snow"
            if background.lower() == 'snow':
                background = 'white'
        
        # Set color
        if colour.startswith('#') and len(colour) == 13:
            # Hex color format
            r, g, b = self.hex48_to_rgb(colour)
            ps.setcolour(r, g, b)
        else:
            # Named color
            ps.setcolour(colour)
        
        # Set font
        ps.setfont(font, args.size)
        
        # Calculate the starting y position based on the number of text lines
        line_spacing = args.size * args.line
        y_position = len(text_lines) * line_spacing
        
        # Add text lines
        for line in text_lines:
            ps.text(10, y_position, line)
            y_position -= line_spacing
        
        # Create output filenames
        ps_file = f"{self.temp_prefix}.ps"
        
        # Write PostScript to file
        ps.output(ps_file)
        
        # Debug: print PS file if requested
        if self.debug:
            print(f"PostScript file generated at: {ps_file}", file=sys.stderr)
            
        # Check if ImageMagick is available
        if False: # shutil.which("convert"):
            # Process with ImageMagick for full portability
            # Build ImageMagick command with all required operations
            im_cmd = ["convert"]
            
            # Set input options
            im_cmd.extend(["-density", "300", ps_file])
            
            # Trim and add border
            im_cmd.extend(["-trim", "+repage", "-bordercolor", "white", "-border", "10"])
            
            # Change background if needed
            if background.lower() != 'white':
                im_cmd.extend(["-background", background, "-alpha", "remove"])
            
            # Rotate if needed
            if args.rotate:
                im_cmd.extend(["-rotate", "270"])
            
            # Set output format
            png_file = f"{self.temp_prefix}.png"
            im_cmd.append(png_file)
            
            # Run the command
            subprocess.run(im_cmd, check=True)
            
            # Convert to final format
            if args.ansi:
                if shutil.which("img2ans"):
                    self.run_prog(f"img2ans -b'{term_background}' {png_file}")
                else:
                    print("Error: img2ans command not found", file=sys.stderr)
                    sys.exit(1)
            else:
                if shutil.which("img2sixel"):
                    self.run_prog(f"img2sixel -I -B '{term_background}' {png_file}")
                else:
                    print("Error: img2sixel command not found", file=sys.stderr)
                    sys.exit(1)
        else:
            # Fallback to netpbm if ImageMagick is not available
            print("Warning: ImageMagick not found, using netpbm tools", file=sys.stderr)
            
            # Use netpbm tools in a pipeline for better performance
            if args.rotate:
                # With rotation
                if background.lower() != 'white':
                    rotate_cmd = f"gs -sDEVICE=ppmraw -sPAPERSIZE=a0 -sOutputFile=- -sNOPAUSE -q -dBATCH {ps_file} | pnmcrop | pnmmargin -white 10 | ppmchange -closeok white '{background}' | pnmrotate -background '{background}' -90 | pnmtopng"
                else:
                    rotate_cmd = f"gs -sDEVICE=ppmraw -sPAPERSIZE=a0 -sOutputFile=- -sNOPAUSE -q -dBATCH {ps_file} | pnmcrop | pnmmargin -white 10 | pnmrotate -background white -90 | pnmtopng"
                
                if args.ansi:
                    # PNG to ANSI
                    if os.path.exists(f"{self.temp_prefix}.png"):
                        os.unlink(f"{self.temp_prefix}.png")
                    self.run_prog(f"{rotate_cmd} > {self.temp_prefix}.png")
                    self.run_prog(f"img2ans -b'{term_background}' {self.temp_prefix}.png")
                else:
                    # PNG to SIXEL - direct pipeline
                    self.run_prog(f"{rotate_cmd} | img2sixel -I -B '{term_background}'")
            else:
                # No rotation needed
                if background.lower() != 'white':
                    cmd = f"gs -sDEVICE=ppmraw -sPAPERSIZE=a0 -sOutputFile=- -sNOPAUSE -q -dBATCH {ps_file} | pnmcrop | pnmmargin -white 10 | ppmchange -closeok white '{background}' | pnmtopng"
                else:
                    cmd = f"gs -sDEVICE=ppmraw -sPAPERSIZE=a0 -sOutputFile=- -sNOPAUSE -q -dBATCH {ps_file} | pnmcrop | pnmmargin -white 10 | pnmtopng"
                
                if args.ansi:
                    # PNG to ANSI
                    if os.path.exists(f"{self.temp_prefix}.png"):
                        os.unlink(f"{self.temp_prefix}.png")
                    self.run_prog(f"{cmd} > {self.temp_prefix}.png")
                    self.run_prog(f"img2ans -b'{term_background}' {self.temp_prefix}.png")
                else:
                    # PNG to SIXEL - direct pipeline
                    self.run_prog(f"{cmd} | img2sixel -I -B '{term_background}'")
        
        # Clean up
        if not self.debug:
            # Clean up temp files
            for ext in ['.ps', '.png', '.log', '.ppm', '.ans', '.six']:
                if os.path.exists(f"{self.temp_prefix}{ext}"):
                    os.unlink(f"{self.temp_prefix}{ext}")
            
            # Remove temp directory if we created one
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        else:
            print(f"Debug: Temporary files kept at {self.temp_prefix}.*", file=sys.stderr)


if __name__ == "__main__":
    bidet = BIDeT()
    bidet.main()