#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIDeT - Use this after you're done with Toilet!
Why did I write this? Because I DEcided To. :)

SYNOPSIS

Use one of these syntaxes:
  bidet [<options>] "<text string>"
  bidet [<options>] <file.txt>
  <command> | bidet [<options>] -
  
Where <options> are one or more of:
  OPTION          MEANING                       DEFAULT
  --ansi          use ANSI instead of SIXEL     False
  --background=b  set background colour to "b"  transparent      
  --colour=c      set text colour to "c"        cornflowerblue
  --font=f        set font face to "f"          Helvetica
  --line=l        set line spacing to l         1
  --preserve      preserve newlines             False
  --rotate        rotate right by 90 degrees    False
  --size=s        set font size to "s"          65
  --width=w       set width to "w"              20
  --help          show this help
  --version       show version
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
        
        # X-Windows colours
        "aliceblue": [240, 248, 255], "antiquewhite": [250, 235, 215], "aqua": [0, 255, 255],
        "aquamarine": [127, 255, 212], "azure": [240, 255, 255], "beige": [245, 245, 220],
        "bisque": [255, 228, 196], "blanchedalmond": [255, 255, 205], "blueviolet": [138, 43, 226],
        "brown": [165, 42, 42], "burlywood": [222, 184, 135], "cadetblue": [95, 158, 160],
        "chartreuse": [127, 255, 0], "chocolate": [210, 105, 30], "coral": [255, 127, 80],
        "cornflowerblue": [100, 149, 237], "cornsilk": [255, 248, 220], "crimson": [220, 20, 60],
        "cyan": [0, 255, 255], "darkcyan": [0, 139, 139], "darkgoldenrod": [184, 134, 11],
        "darkgray": [169, 169, 169], "darkgrey": [169, 169, 169], "darkkhaki": [189, 183, 107],
        "darkmagenta": [139, 0, 139], "darkolivegreen": [85, 107, 47], "darkorange": [255, 140, 0],
        "darkorchid": [153, 50, 204], "darksalmon": [233, 150, 122], "darkseagreen": [143, 188, 143],
        "darkslateblue": [72, 61, 139], "darkslategray": [47, 79, 79], "darkslategrey": [47, 79, 79],
        "darkturquoise": [0, 206, 209], "darkviolet": [148, 0, 211], "deeppink": [255, 20, 147],
        "deepskyblue": [0, 191, 255], "dimgray": [105, 105, 105], "dimgrey": [105, 105, 105],
        "dodgerblue": [30, 144, 255], "firebrick": [178, 34, 34], "floralwhite": [255, 250, 240],
        "forestgreen": [34, 139, 34], "fuchsia": [255, 0, 255], "gainsboro": [220, 220, 220],
        "ghostwhite": [248, 248, 255], "gold": [255, 215, 0], "goldenrod": [218, 165, 32],
        "gray": [128, 128, 128], "grey": [128, 128, 128], "greenyellow": [173, 255, 47],
        "honeydew": [240, 255, 240], "hotpink": [255, 105, 180], "indianred": [205, 92, 92],
        "indigo": [75, 0, 130], "ivory": [255, 240, 240], "khaki": [240, 230, 140],
        "lavender": [230, 230, 250], "lavenderblush": [255, 240, 245], "lawngreen": [124, 252, 0],
        "lemonchiffon": [255, 250, 205], "lightblue": [173, 216, 230], "lightcoral": [240, 128, 128],
        "lightcyan": [224, 255, 255], "lightgoldenrodyellow": [250, 250, 210], "lightgray": [211, 211, 211],
        "lightgreen": [144, 238, 144], "lightgrey": [211, 211, 211], "lightpink": [255, 182, 193],
        "lightsalmon": [255, 160, 122], "lightseagreen": [32, 178, 170], "lightskyblue": [135, 206, 250],
        "lightslategray": [119, 136, 153], "lightslategrey": [119, 136, 153], "lightsteelblue": [176, 196, 222],
        "lightyellow": [255, 255, 224], "lime": [0, 255, 0], "limegreen": [50, 205, 50],
        "linen": [250, 240, 230], "magenta": [255, 0, 255], "maroon": [128, 0, 0],
        "mediumaquamarine": [102, 205, 170], "mediumblue": [0, 0, 205], "mediumorchid": [186, 85, 211],
        "mediumpurple": [147, 112, 219], "mediumseagreen": [60, 179, 113], "mediumslateblue": [123, 104, 238],
        "mediumspringgreen": [0, 250, 154], "mediumturquoise": [72, 209, 204], "mediumvioletred": [199, 21, 133],
        "midnightblue": [25, 25, 112], "mintcream": [245, 255, 250], "mistyrose": [255, 228, 225],
        "moccasin": [255, 228, 181], "navajowhite": [255, 222, 173], "navy": [0, 0, 128],
        "oldlace": [253, 245, 230], "olive": [128, 128, 0], "olivedrab": [107, 142, 35],
        "orange": [255, 165, 0], "orangered": [255, 69, 0], "orchid": [218, 112, 214],
        "palegoldenrod": [238, 232, 170], "palegreen": [152, 251, 152], "paleturquoise": [175, 238, 238],
        "palevioletred": [219, 112, 147], "papayawhip": [255, 239, 213], "peachpuff": [255, 218, 185],
        "peru": [205, 133, 63], "pink": [255, 192, 203], "plum": [221, 160, 221],
        "powderblue": [176, 224, 230], "purple": [128, 0, 128], "rosybrown": [188, 143, 143],
        "royalblue": [65, 105, 225], "saddlebrown": [139, 69, 19], "salmon": [250, 128, 114],
        "sandybrown": [244, 164, 96], "seagreen": [46, 139, 87], "seashell": [255, 245, 238],
        "sienna": [160, 82, 45], "silver": [192, 192, 192], "skyblue": [135, 206, 235],
        "slateblue": [106, 90, 205], "slategray": [112, 128, 144], "slategrey": [112, 128, 144],
        "snow": [255, 250, 250], "springgreen": [0, 255, 127], "steelblue": [70, 130, 180],
        "tan": [210, 180, 140], "teal": [0, 128, 128], "thistle": [216, 191, 216],
        "tomato": [253, 99, 71], "turquoise": [64, 224, 208], "violet": [238, 130, 238],
        "wheat": [245, 222, 179], "whitesmoke": [245, 245, 245], "yellow": [255, 255, 0],
        "yellowgreen": [154, 205, 50],
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
            # Mock response for testing
            if not shutil.which("test-sixel"):
                print("Warning: test-sixel command not found, using defaults", file=sys.stderr)
                return "black", "white"
                
            result = subprocess.run(["test-sixel"], capture_output=True, text=True)
            output = result.stdout.strip()
            
            match = re.search(r'Sixel support found. fg=(\S+) bg=(\S+) nc=(\S+)', output)
            if match:
                return match.group(1), match.group(2)
            else:
                print("Warning: Sixel support not detected, using defaults", file=sys.stderr)
                return "black", "white"
        except Exception as e:
            print(f"Warning: Error checking Sixel support: {e}", file=sys.stderr)
            return "black", "white"
    
    def collapse_or_find_font(self, mode, font, available_fonts):
        """Collapse font names or find a matching font
        
        Args:
            mode: "collapse" or "search"
            font: Font name to search for (if mode is "search")
            available_fonts: List of available fonts
            
        Returns:
            Either a list of collapsed fonts or a single matching font
        """
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
        """Test if font is valid and potentially list available fonts
        
        Args:
            font: Font name or "list" to list fonts
            iso: Whether ISO Latin1 encoding is needed
            
        Returns:
            Valid font name
        """
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
        """Test if colors are valid and potentially list available colors
        
        Args:
            colour: Text color or "list"/"random"
            background: Background color or "list"/"random"
            
        Returns:
            Tuple of (colour, background)
        """
        colour = colour.lower()
        background = background.lower()
        
        # Get colour lists
        colours = list(PostScriptSimple.pscolours.keys())
        
        # Get backgrounds from netpbm
        try:
            rgb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'netpbm_rgb.txt')
            if not os.path.exists(rgb_path):
                # Fallback to system location
                rgb_path = '/usr/share/netpbm/rgb.txt'
                
            if os.path.exists(rgb_path):
                with open(rgb_path, 'r') as f:
                    backgrounds = []
                    for line in f:
                        match = re.search(r'^\s*\d+\s+\d+\s+\d+\s+(\w+)', line)
                        if match:
                            backgrounds.append(match.group(1).lower())
            else:
                backgrounds = colours  # Fallback
        except FileNotFoundError:
            backgrounds = colours  # Fallback
        
        # Find common colors
        both = [c for c in colours if c.lower() in backgrounds]
        
        # List colors
        if colour == "list" or background == "list":
            for c in sorted(both):
                print(c)
            sys.exit(0)
        
        # Random colors
        if colour == "random":
            colour = random.choice(both)
        if background == "random":
            background = random.choice(both)
        
        # Check colour
        if colour != 'default' and colour not in both:
            print(f"Error: Invalid colour: {colour}", file=sys.stderr)
            sys.exit(1)
        
        # Check background
        if background != 'transparent' and background not in both:
            print(f"Error: Invalid background: {background}", file=sys.stderr)
            sys.exit(1)
        
        # Make sure not same
        if colour == background and colour != 'default' and background != 'transparent':
            print(f"Error: colour and background cannot be the same", file=sys.stderr)
            sys.exit(1)
        
        return colour, background
    
    def hex48_to_rgb(self, hex_str):
        """Convert 48-bit hex color to RGB values
        
        Args:
            hex_str: Hex color string like #000000000000
            
        Returns:
            Tuple of (r, g, b) values (0-255)
        """
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
        """Run a command and check for errors
        
        Args:
            cmd: Command to run
        """
        log_file = f"{self.temp_prefix}.log"
        
        if self.debug:
            print(f"CMD={cmd}", file=sys.stderr)
        
        # Run command and redirect stderr to log
        with open(log_file, 'a') as log:
            proc = subprocess.run(cmd, shell=True, stderr=log)
        
        # Check if there were errors
        if os.path.getsize(log_file) > 0:
            print(f"Error: System call failed: {cmd}", file=sys.stderr)
            with open(log_file, 'r') as log:
                print(log.read(), file=sys.stderr)
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
        
        # Write to file
        ps_file = f"{self.temp_prefix}.ps"
        ps.output(ps_file)
        
        # Debug: print PS file if requested
        if self.debug:
            print(f"PostScript file generated at: {ps_file}", file=sys.stderr)
            with open(ps_file, 'r') as f:
                print(f.read())
        
        # Clear log file
        with open(f"{self.temp_prefix}.log", 'w') as f:
            pass
        
        # Convert PS to PPM
        gs_cmd = f"gs -sDEVICE=ppmraw -sPAPERSIZE=a0 -sOutputFile={self.temp_prefix}.ppm -sNOPAUSE -q -dBATCH {ps_file}"
        self.run_prog(gs_cmd)
        
        # Apply cropping
        self.run_prog(f"pnmcrop < {self.temp_prefix}.ppm | pnmmargin -white 10 > {self.temp_prefix}_cropped.ppm")
        self.run_prog(f"mv {self.temp_prefix}_cropped.ppm {self.temp_prefix}.ppm")
        
        # Change background if needed
        if background.lower() != 'white':
            self.run_prog(f"ppmchange -closeok white '{background}' < {self.temp_prefix}.ppm > {self.temp_prefix}_bg.ppm")
            self.run_prog(f"mv {self.temp_prefix}_bg.ppm {self.temp_prefix}.ppm")
        
        # Rotate if needed
        if args.rotate:
            # Check if we have proper netpbm
            try:
                proc = subprocess.run(["pamcomp", "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if proc.returncode == 0:
                    self.run_prog(f"pnmrotate -background '{background}' -90 < {self.temp_prefix}.ppm > {self.temp_prefix}_rotated.ppm")
                    self.run_prog(f"mv {self.temp_prefix}_rotated.ppm {self.temp_prefix}.ppm")
                else:
                    print("Note: Unable to rotate - pamcomp not working correctly.", file=sys.stderr)
            except FileNotFoundError:
                print("Note: You have the lobotomized Debian netpbm. Features are greatly restricted.", file=sys.stderr)
        
        # Convert PPM to PNG
        self.run_prog(f"pnmtopng < {self.temp_prefix}.ppm > {self.temp_prefix}.png")
        
        # Output the result
        if args.ansi:
            # Check if img2ans exists
            if not shutil.which("img2ans"):
                print("Error: img2ans command not found", file=sys.stderr)
                sys.exit(1)
                
            # PNG to ANSI
            self.run_prog(f"img2ans -b'{term_background}' {self.temp_prefix}.png > {self.temp_prefix}.ans")
            with open(f"{self.temp_prefix}.ans", 'r', encoding='latin1') as f:
                sys.stdout.write(f.read())
        else:
            # Check if img2sixel exists
            if not shutil.which("img2sixel"):
                print("Error: img2sixel command not found", file=sys.stderr)
                sys.exit(1)
                
            # PNG to SIXEL
            self.run_prog(f"img2sixel -I -B '{term_background}' < {self.temp_prefix}.png > {self.temp_prefix}.six")
            with open(f"{self.temp_prefix}.six", 'r', encoding='latin1') as f:
                sys.stdout.write(f.read())
        
        # Clean up
        if not self.debug:
            shutil.rmtree(self.temp_dir)
        else:
            print(f"Debug: Temporary files kept in {self.temp_dir}", file=sys.stderr)


if __name__ == "__main__":
    bidet = BIDeT()
    bidet.main()