#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIDeT - Use this after you're done with Toilet!
Enhanced version with multiple effects.
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
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageOps, ImageFont, ImageColor
import math
import io
import time

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


class EffectsProcessor:
    """Process image effects with Pillow"""
    
    # Available patterns for backgrounds
    patterns = [
        "checkerboard", "dots", "grid", "stripes", "waves", 
        "zigzag", "crosshatch", "bricks", "diamonds", "bubbles"
    ]
    
    def __init__(self, debug=False):
        self.debug = debug
    
    def _create_pattern_image(self, pattern_name, size, color1, color2, scale=20):
        """Create a pattern image
        
        Args:
            pattern_name: Name of the pattern
            size: (width, height) tuple
            color1, color2: Colors for the pattern
            scale: Pattern scale factor
            
        Returns:
            PIL Image with the pattern
        """
        width, height = size
        img = Image.new('RGBA', size, color1)
        draw = ImageDraw.Draw(img)
        
        if pattern_name == "checkerboard":
            # Checkerboard pattern
            for y in range(0, height, scale):
                for x in range(0, width, scale):
                    if (x // scale + y // scale) % 2 == 0:
                        draw.rectangle([x, y, x + scale - 1, y + scale - 1], fill=color2)
        
        elif pattern_name == "dots":
            # Dots pattern
            dot_radius = scale // 2
            for y in range(dot_radius, height, scale):
                for x in range(dot_radius, width, scale):
                    draw.ellipse([x - dot_radius, y - dot_radius, 
                                  x + dot_radius, y + dot_radius], fill=color2)
        
        elif pattern_name == "grid":
            # Grid pattern
            for y in range(0, height, scale):
                draw.line([(0, y), (width, y)], fill=color2, width=1)
            for x in range(0, width, scale):
                draw.line([(x, 0), (x, height)], fill=color2, width=1)
        
        elif pattern_name == "stripes":
            # Stripes pattern
            for y in range(0, height, scale*2):
                draw.rectangle([0, y, width, y + scale - 1], fill=color2)
        
        elif pattern_name == "waves":
            # Waves pattern
            for y in range(0, height, scale):
                points = []
                for x in range(0, width + scale, scale//2):
                    points.append((x, y + int(math.sin(x * 0.05) * scale/2)))
                if len(points) > 1:
                    draw.line(points, fill=color2, width=2)
        
        elif pattern_name == "zigzag":
            # Zigzag pattern
            for y_offset in range(0, height, scale*2):
                points = []
                for x in range(0, width + scale, scale):
                    y = y_offset + (scale if x % (scale*2) == 0 else 0)
                    points.append((x, y))
                if len(points) > 1:
                    draw.line(points, fill=color2, width=2)
        
        elif pattern_name == "crosshatch":
            # Crosshatch pattern
            for y in range(-height, height*2, scale):
                draw.line([(0, y), (width, y + width)], fill=color2, width=1)
                draw.line([(0, y + width), (width, y)], fill=color2, width=1)
        
        elif pattern_name == "bricks":
            # Bricks pattern
            brick_height = scale
            brick_width = scale * 2
            for y in range(0, height, brick_height):
                offset = 0 if (y // brick_height) % 2 == 0 else brick_width // 2
                for x in range(-offset, width, brick_width):
                    draw.rectangle([x, y, x + brick_width - 1, y + brick_height - 1], 
                                   outline=color2, width=1)
        
        elif pattern_name == "diamonds":
            # Diamonds pattern
            for y in range(0, height, scale):
                for x in range(0, width, scale):
                    draw.polygon([(x + scale/2, y), (x + scale, y + scale/2), 
                                   (x + scale/2, y + scale), (x, y + scale/2)], 
                                 fill=color2)
        
        elif pattern_name == "bubbles":
            # Random bubbles pattern
            import random
            for _ in range(width * height // (scale * scale)):
                x = random.randint(0, width)
                y = random.randint(0, height)
                radius = random.randint(scale//4, scale//2)
                draw.ellipse([x - radius, y - radius, x + radius, y + radius], 
                             fill=color2, outline=color1)
        
        return img
    
    def _get_rgb_color(self, color_name):
        """Convert color name to RGB tuple
        
        Args:
            color_name: Color name or hex value
            
        Returns:
            RGB tuple
        """
        if color_name in PostScriptSimple.pscolours:
            return tuple(PostScriptSimple.pscolours[color_name])
        
        try:
            # Try to parse as hex color
            return ImageColor.getrgb(color_name)
        except:
            print(f"Warning: Unknown color '{color_name}', using black", file=sys.stderr)
            return (0, 0, 0)
    
    def _make_transparent_background(self, img):
        """Make the white background transparent
        
        Args:
            img: PIL Image
            
        Returns:
            PIL Image with transparent background
        """
        img = img.convert("RGBA")
        datas = img.getdata()
        
        new_data = []
        for item in datas:
            # Change all white (or nearly white) pixels to transparent
            if item[0] > 240 and item[1] > 240 and item[2] > 240:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
                
        img.putdata(new_data)
        return img

    def render_ps_to_image(self, ps_file):
        """Render PostScript to PNG using Ghostscript
        
        Args:
            ps_file: PostScript file
            
        Returns:
            PIL Image
        """
        # Create a temporary file for the output
        temp_png = f"{ps_file}.png"
        
        # Use Ghostscript to render the PS to PNG
        gs_cmd = [
            "gs", 
            "-dSAFER",
            "-dBATCH", 
            "-dNOPAUSE", 
            "-sDEVICE=pngalpha", 
            "-r300", 
            f"-sOutputFile={temp_png}",
            ps_file
        ]
        
        if self.debug:
            print(f"Running: {' '.join(gs_cmd)}", file=sys.stderr)
        
        proc = subprocess.run(gs_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if proc.returncode != 0:
            print(f"Error: Failed to render PostScript: {proc.stderr.decode()}", file=sys.stderr)
            sys.exit(1)
            
        # Load the PNG data into PIL
        try:
            img = Image.open(temp_png)
            
            # Make white background transparent
            img = self._make_transparent_background(img)
            
            # Auto-crop the image
            if img.mode == 'RGBA':
                # Get the alpha channel
                alpha = img.split()[3]
                # Get the bounding box of non-transparent pixels
                bbox = alpha.getbbox()
                if bbox:
                    # Crop to bounding box
                    img = img.crop(bbox)
            else:
                # For non-RGBA images, use the normal crop function
                bbox = ImageOps.invert(img.convert('L')).getbbox()
                if bbox:
                    img = img.crop(bbox)
            
            # Add a small padding
            padding = 10
            padded_size = (img.width + padding*2, img.height + padding*2)
            padded_img = Image.new('RGBA', padded_size, (255, 255, 255, 0))
            padded_img.paste(img, (padding, padding), img if img.mode == 'RGBA' else None)
            
            # Clean up the temporary PNG file unless in debug mode
            if not self.debug and os.path.exists(temp_png):
                os.unlink(temp_png)
                
            return padded_img
            
        except Exception as e:
            print(f"Error: Failed to process image: {e}", file=sys.stderr)
            sys.exit(1)    

    def apply_effects(self, img, effects):
        """Apply various effects to the image
        
        Args:
            img: PIL Image
            effects: Dictionary of effects to apply
            
        Returns:
            PIL Image with effects applied
        """
        # Make a copy to work with
        result = img.copy()
        
        # Apply flip if requested
        if effects.get('flip'):
            flip_type = effects['flip']
            if flip_type == 'horizontal':
                result = ImageOps.mirror(result)
            elif flip_type == 'vertical':
                result = ImageOps.flip(result)
            elif flip_type == 'both':
                result = ImageOps.flip(ImageOps.mirror(result))
        
        # Apply color spill (gradient) if requested
        if effects.get('colorspill'):
            spill_colors = effects['colorspill'].split(',')
            if len(spill_colors) == 2:
                color1 = self._get_rgb_color(spill_colors[0])
                color2 = self._get_rgb_color(spill_colors[1])
                
                # Create a gradient mask
                gradient = Image.new('L', result.size, 0)
                draw = ImageDraw.Draw(gradient)
                
                for y in range(result.height):
                    # Calculate gradient intensity (0-255)
                    intensity = int(255 * y / result.height)
                    draw.line([(0, y), (result.width, y)], fill=intensity)
                
                # Create gradient overlay image
                gradient_img = Image.new('RGBA', result.size)
                for y in range(result.height):
                    # Calculate interpolation factor (0.0-1.0)
                    t = y / result.height
                    # Linear interpolation between colors
                    r = int(color1[0] * (1-t) + color2[0] * t)
                    g = int(color1[1] * (1-t) + color2[1] * t)
                    b = int(color1[2] * (1-t) + color2[2] * t)
                    # Draw a line of this color
                    ImageDraw.Draw(gradient_img).line(
                        [(0, y), (result.width, y)], fill=(r, g, b, 128))
                
                # Apply gradient overlay where the original image has content
                if result.mode == 'RGBA':
                    # Get the alpha channel of the original image
                    alpha = result.split()[3]
                    # Create a new image for the result
                    new_img = Image.new('RGBA', result.size, (0, 0, 0, 0))
                    # Paste the gradient using the original alpha as mask
                    new_img.paste(gradient_img, (0, 0), alpha)
                    # Blend with the original
                    result = Image.alpha_composite(result, new_img)
        
        # Apply pattern to background if requested
        if effects.get('pattern'):
            pattern_name = effects['pattern']
            if pattern_name in self.patterns:
                # Get pattern colors
                pattern_colors = effects.get('pattern_colors', 'white,black').split(',')
                color1 = self._get_rgb_color(pattern_colors[0])
                color2 = self._get_rgb_color(pattern_colors[1] if len(pattern_colors) > 1 else 'black')
                
                # Create pattern image
                pattern_scale = int(effects.get('pattern_scale', '20'))
                pattern_img = self._create_pattern_image(
                    pattern_name, result.size, color1 + (255,), color2 + (255,), pattern_scale)
                
                # Create a composite with the pattern as background
                if result.mode == 'RGBA':
                    # Create a new image with the pattern
                    new_img = pattern_img.copy()
                    # Paste the original image on top
                    new_img.alpha_composite(result)
                    result = new_img
        
        # Apply tiling if requested
        if effects.get('tile'):
            tile_type = effects['tile']
            tile_count = int(effects.get('tile_count', '3'))
            
            # Create a larger canvas
            if tile_type == 'grid':
                # Create a grid of tiles
                tile_size = (result.width, result.height)
                new_size = (tile_size[0] * tile_count, tile_size[1] * tile_count)
                tiled_img = Image.new('RGBA', new_size, (0, 0, 0, 0))
                
                for y in range(0, new_size[1], tile_size[1]):
                    for x in range(0, new_size[0], tile_size[0]):
                        tiled_img.paste(result, (x, y), result if result.mode == 'RGBA' else None)
                
                result = tiled_img
                
            elif tile_type == 'mirror':
                # Create a mirrored tile pattern
                tile_size = (result.width, result.height)
                new_size = (tile_size[0] * tile_count, tile_size[1] * tile_count)
                tiled_img = Image.new('RGBA', new_size, (0, 0, 0, 0))
                
                for y in range(tile_count):
                    for x in range(tile_count):
                        # Determine which variant to use based on position
                        img_to_paste = result
                        if x % 2 == 1:
                            img_to_paste = ImageOps.mirror(img_to_paste)
                        if y % 2 == 1:
                            img_to_paste = ImageOps.flip(img_to_paste)
                        
                        tiled_img.paste(img_to_paste, 
                                       (x * tile_size[0], y * tile_size[1]), 
                                       img_to_paste if img_to_paste.mode == 'RGBA' else None)
                
                result = tiled_img
        
        # Apply color fade if requested
        if effects.get('fade'):
            fade_type = effects['fade']
            fade_amount = float(effects.get('fade_amount', '0.5'))
            
            if fade_type == 'transparent':
                # Increase transparency
                if result.mode == 'RGBA':
                    r, g, b, a = result.split()
                    a = ImageEnhance.Brightness(a).enhance(1.0 - fade_amount)
                    result = Image.merge('RGBA', (r, g, b, a))
            
            elif fade_type == 'white':
                # Fade to white
                enhancer = ImageEnhance.Contrast(result)
                result = enhancer.enhance(1.0 - fade_amount)
                
                if result.mode == 'RGBA':
                    enhancer = ImageEnhance.Brightness(result)
                    result = enhancer.enhance(1.0 + fade_amount)
            
            elif fade_type == 'black':
                # Fade to black
                enhancer = ImageEnhance.Brightness(result)
                result = enhancer.enhance(1.0 - fade_amount)
        
        # Apply shadow/3D effect if requested
        if effects.get('shadow'):
            shadow_type = effects['shadow']
            shadow_offset = int(effects.get('shadow_offset', '5'))
            shadow_color = self._get_rgb_color(effects.get('shadow_color', 'black')) + (128,)  # Add alpha
            
            if shadow_type == 'drop':
                # Create a shadow by offsetting a darkened copy
                shadow = Image.new('RGBA', result.size, (0, 0, 0, 0))
                shadow_mask = result.split()[3] if result.mode == 'RGBA' else Image.new('L', result.size, 0)
                
                # Create a new canvas large enough for image and shadow
                new_size = (result.width + shadow_offset, result.height + shadow_offset)
                new_img = Image.new('RGBA', new_size, (0, 0, 0, 0))
                
                # Create the shadow
                shadow = Image.new('RGBA', result.size, shadow_color)
                
                # Paste shadow first, then original image
                new_img.paste(shadow, (shadow_offset, shadow_offset), shadow_mask)
                new_img.paste(result, (0, 0), result if result.mode == 'RGBA' else None)
                
                result = new_img
                
            elif shadow_type == '3d':
                # Create a 3D effect with multiple layers
                layers = 5
                step = max(1, shadow_offset // layers)
                
                # Create a new canvas large enough for all layers
                new_size = (result.width + shadow_offset, result.height + shadow_offset)
                new_img = Image.new('RGBA', new_size, (0, 0, 0, 0))
                
                # Get alpha mask
                shadow_mask = result.split()[3] if result.mode == 'RGBA' else Image.new('L', result.size, 0)
                
                # Add shadow layers from back to front
                for i in range(layers, 0, -1):
                    offset = i * step
                    shadow_color_with_alpha = shadow_color[0:3] + (int(128 * (i / layers)),)
                    shadow = Image.new('RGBA', result.size, shadow_color_with_alpha)
                    new_img.paste(shadow, (offset, offset), shadow_mask)
                
                # Finally add the original image on top
                new_img.paste(result, (0, 0), result if result.mode == 'RGBA' else None)
                
                result = new_img
        
        return result
    
    def save_image(self, img, output_file, format='PNG'):
        """Save the image to a file
        
        Args:
            img: PIL Image
            output_file: Output filename
            format: Image format (PNG, JPEG, etc.)
            
        Returns:
            Path to the saved file
        """
        try:
            img.save(output_file, format=format)
            return output_file
        except Exception as e:
            print(f"Error: Failed to save image: {e}", file=sys.stderr)
            sys.exit(1)
    
    def img_to_sixel(self, img, bg_color):
        """Convert PIL image to Sixel and output to stdout
        
        Args:
            img: PIL Image
            bg_color: Background color for Sixel
        """
        # Save to a temporary PNG file
        temp_file = tempfile.mktemp(suffix='.png')
        self.save_image(img, temp_file)
        
        # Check if img2sixel exists
        if not shutil.which("img2sixel"):
            print("Error: img2sixel command not found", file=sys.stderr)
            sys.exit(1)
        
        # Run img2sixel
        try:
            subprocess.run(["img2sixel", "-I", "-B", bg_color, temp_file], check=True)
        except Exception as e:
            print(f"Error: Failed to convert to Sixel: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            # Remove temporary file
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def img_to_ansi(self, img, bg_color):
        """Convert PIL image to ANSI and output to stdout
        
        Args:
            img: PIL Image
            bg_color: Background color for ANSI
        """
        # Save to a temporary PNG file
        temp_file = tempfile.mktemp(suffix='.png')
        self.save_image(img, temp_file)
        
        # Check if img2ans exists
        if not shutil.which("img2ans"):
            print("Error: img2ans command not found", file=sys.stderr)
            sys.exit(1)
        
        # Run img2ans
        try:
            subprocess.run(["img2ans", "-b", bg_color, temp_file], check=True)
        except Exception as e:
            print(f"Error: Failed to convert to ANSI: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            # Remove temporary file
            if os.path.exists(temp_file):
                os.unlink(temp_file)


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
    
    def list_patterns(self):
        """List available patterns"""
        print("Available patterns:")
        for p in EffectsProcessor.patterns:
            print(f"  - {p}")
        sys.exit(0)
    
    def check_required_tools(self):
        """Check if required tools are available"""
        missing_tools = []
        
        # Check for Ghostscript
        if not shutil.which("gs"):
            missing_tools.append("gs (Ghostscript)")
        
        # Check for image conversion tools
        if not shutil.which("img2sixel") and not shutil.which("img2ans"):
            missing_tools.append("img2sixel or img2ans")
        
        if missing_tools:
            print(f"Error: Missing required tools: {', '.join(missing_tools)}", file=sys.stderr)
            print("Please install the necessary packages", file=sys.stderr)
            sys.exit(1)
    
    def main(self):
        """Main function"""
        parser = argparse.ArgumentParser(description='BIDeT - Use this after you\'re done with Toilet!')
        
        # Basic options
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
        
        # New effects options
        parser.add_argument('--flip', choices=['horizontal', 'vertical', 'both'], 
                          help='Flip the image')
        parser.add_argument('--colorspill', metavar='COLOR1,COLOR2',
                          help='Apply a color gradient (e.g., red,blue)')
        parser.add_argument('--pattern', metavar='PATTERN',
                          help='Add pattern to background')
        parser.add_argument('--pattern-colors', metavar='COLOR1,COLOR2', default='white,black',
                          help='Colors for the pattern (default: white,black)')
        parser.add_argument('--pattern-scale', type=int, default=20,
                          help='Scale factor for pattern (default: 20)')
        parser.add_argument('--list-patterns', action='store_true',
                          help='List available patterns')
        parser.add_argument('--tile', choices=['grid', 'mirror'],
                          help='Tile the image in a grid or mirrored pattern')
        parser.add_argument('--tile-count', type=int, default=3,
                          help='Number of tiles in each direction (default: 3)')
        parser.add_argument('--fade', choices=['transparent', 'white', 'black'],
                          help='Apply a fade effect')
        parser.add_argument('--fade-amount', type=float, default=0.5,
                          help='Amount of fading (0.0-1.0, default: 0.5)')
        parser.add_argument('--shadow', choices=['drop', '3d'],
                          help='Add a shadow or 3D effect')
        parser.add_argument('--shadow-offset', type=int, default=5,
                          help='Shadow offset in pixels (default: 5)')
        parser.add_argument('--shadow-color', default='black',
                          help='Shadow color (default: black)')
        
        parser.add_argument('text', nargs='*', help='Text to display or filename')
        
        args = parser.parse_args()
        
        # Set up debug mode
        self.debug = args.debug
        
        # Show version
        if args.version:
            print("Version: 2.0")
            sys.exit(0)
        
        # List patterns if requested
        if args.list_patterns:
            self.list_patterns()
        
        # Check for required tools
        self.check_required_tools()
        
        # Create temp directory for files
        if os.path.exists("/dev/shm"):
            # Use /dev/shm for better performance on Linux
            shm_path = f"/dev/shm/{os.environ.get('USER', 'bidet')}"
            os.makedirs(shm_path, exist_ok=True)
            self.temp_prefix = os.path.join(shm_path, f"bidet_tmp_{int(time.time())}")
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
        
        # Create effects processor
        effects_processor = EffectsProcessor(debug=self.debug)
        
        # Render PostScript to image
        img = effects_processor.render_ps_to_image(ps_file)
        
        # Handle rotation before effects
        if args.rotate:
            img = img.rotate(270, expand=True)
        
        # Collect effects to apply
        effects = {}
        if args.flip:
            effects['flip'] = args.flip
        if args.colorspill:
            effects['colorspill'] = args.colorspill
        if args.pattern:
            effects['pattern'] = args.pattern
            effects['pattern_colors'] = args.pattern_colors
            effects['pattern_scale'] = args.pattern_scale
        if args.tile:
            effects['tile'] = args.tile
            effects['tile_count'] = args.tile_count
        if args.fade:
            effects['fade'] = args.fade
            effects['fade_amount'] = args.fade_amount
        if args.shadow:
            effects['shadow'] = args.shadow
            effects['shadow_offset'] = args.shadow_offset
            effects['shadow_color'] = args.shadow_color
        
        # Apply effects if any
        if effects:
            img = effects_processor.apply_effects(img, effects)
        
        # Save debug image if requested
        if self.debug:
            debug_file = f"{self.temp_prefix}_final.png"
            effects_processor.save_image(img, debug_file)
            print(f"Final image saved to: {debug_file}", file=sys.stderr)
        
        # Output image
        if args.ansi:
            effects_processor.img_to_ansi(img, background)
        else:
            effects_processor.img_to_sixel(img, background)
        
        # Clean up
        if not self.debug:
            # Clean up temp files
            for ext in ['.ps', '.png', '.log', '.ppm', '.ans', '.six']:
                if os.path.exists(f"{self.temp_prefix}{ext}"):
                    try:
                        os.unlink(f"{self.temp_prefix}{ext}")
                    except:
                        pass
            
            # Remove temp directory if we created one
            if self.temp_dir and os.path.exists(self.temp_dir):
                try:
                    shutil.rmtree(self.temp_dir)
                except:
                    pass


if __name__ == "__main__":
    bidet = BIDeT()
    bidet.main()