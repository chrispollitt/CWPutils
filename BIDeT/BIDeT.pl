#!/usr/bin/env2 perl -CA
#
# BIDeT - Use this after you're done with Toilet!
#

=pod

=encoding utf8

=head1 NAME

B<BIDeT> - Use this after you're done with Toilet!
Why did I write this? Because I DEcided To. :)

=head1 SYNOPSIS

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
  --rotate        rotate rigt by 90 degrees     False
  --size=s        set font size to "s"          65
  --width=w       set width to "w"              20
  --help          show this help
  --version       show version

Notes:

  Option names can be shortened to the first letter and used with a single dash:
  --background=b becomes -b b
  
  To list available fonts, use -f list
  To list available colours/backgrounds, use -c list
  To get a random value for any of these, use -c/-b/-f random
  
  If you use Latin1 characters, the available fonts is reduced. The input should
  be in UTF-8 and it will be converted to Latin1.

=head1 REQUIREMENTS

=over 4

=item * Perl

=item * GhostScript

=item * Sponge (Part of MoreUtils package)

=item * Netpbm package

NOTE! The default version on Debian/Ubuntu has been lobotomized. 
Features will be greatly restricted. To remedy, follow these steps:

  1. sudo apt remove netpbm libnetpbm10
  2. wget -O netpbm-sf-10.73.33_amd64.deb https://sourceforge.net/projects/netpbm/files/super_stable/10.73.33/netpbm-sf-10.73.33_amd64.deb/download
  3. sudo apt install libpng16-16 libjpeg62
  4. sudo dpkg -i ./netpbm-sf-10.73.33_amd64.deb
  5. sudo chown -R root.root /usr/share/netpbm
  6. sudo chmod -R ugo+rX /usr/share/netpbm

=item * img2sixel (Part of libsixel-bin package)

=item * a terminal that handles Sixel graphics

These are known to work:

=over 4

=item - mintty  (Cygwin)

=item - mlterm  (Linux, Solaris)

=item - iTerm2  (macOS)

=back

=back

=head1 BACKGROUND

In 1983 AT&T released banner(1) with UNIX System V. It allowed you to create a
banner of text made out of ascii characters.

In 1987 DEC released the VT300 series of  computer terminals. These came with
the ability to display graphics via the new Sixel encoding format.

In 1991 Chappell and Chai releaed FIGlet(1) as an extension of banner(1) that had
numerous "fonts."

In 2004 Sam Hocevar releaed TOIlet(1) as an extention of FIGlet(1). It has
more fonts, colour and other neat features.

In 2014 Hayaki Saito wrote the img2sixel(1) utility.

In 2016 Hayaki Saito added Sixel graphics support to mintty(1).

In 2020 Chris Pollitt releaed BIDeT(1) as an alternative to TOIlet(1). It makes use
of sixel graphics to display Type 1 Postscript fonts.

=head1 TO DO

=over 4

=item * Add additonal fonts

=item * Add additonal effects (borders, ppmpat/pnmtile, etc.)

=item * make sure terminal is capable of displaying sixel graphics

=back

=head1 AUTHOR

Chris Pollitt https://github.com/chrispollitt/

=cut

# Pragmas
use strict;
use warnings;
use FindBin qw($Bin);
use lib "$Bin";
binmode STDIN,  ':encoding(UTF-8)';
binmode STDOUT, ':encoding(Latin1)';

# Includes
use Getopt::Long;
use Text::Wrap;
use PostScript_Simple;
#use IO::Select;
use Pod::Usage;
use File::Basename;
use File::Slurper 'read_lines';

our $file;
our $debug      = 0;

# Usage ####################################################
sub usage {
  my($version)=@_;
  
  if($version) {
    print "Version: 1.3\n";
  } else {
    pod2usage(
      -indent => 0,
    );
  }
  exit(1);
}

# See if we have a sixel capable terminal ###########################
sub test_sixel {
	my $out=`test-sixel`;
	chomp($out);
	my($fg,$bg);
	if($out =~ /Sixel support found. fg=(\S+) bg=(\S+) nc=(\S+)/) {
		$fg = $1;
		$bg = $2;
	} else {
		die("error: Sixel not supported\n");
	}
	return ($fg,$bg);
}

# See if we have input on stdin ###########################
sub test_stdin {
  my $timeout = 0.3;  # Best to use "-" as filename to force STDIN
  my $s = IO::Select->new();
  
  $s->add(\*STDIN);
  if ($s->can_read($timeout)) {
    return(1);
  }
  return(0);
}

# Collapse or find closest font ############################
sub collapse_or_find_font {
  my ($mode, $font, @available_fonts) = @_;
  my %seen;
  my @collapsed_fonts;
	my @types = read_lines('/usr/local/share/BIDeT/fontsuffixlist.txt');
	# sort by length
  @types = sort { length($b) <=> length($a) } @types;
	# collapse
  if ($mode eq "collapse") {
    # Collapse fonts mode
    my %seen;
    my @collapsed_fonts;
    foreach my $font (@available_fonts) {
      # Remove specified suffixes
      foreach my $type (@types) {
        if ($font =~ s/-?\Q$type\E$//) {
          last;  # Exit the loop after the first match
        }
      }
      # Add the base font to the collapsed list if not already seen
      unless ($seen{$font}) {
        push @collapsed_fonts, $font;
        $seen{$font} = 1;
      }
    }
    return @collapsed_fonts;
  # search
  } elsif ($mode eq "search") {
    # Find closest font mode
    # Check each suffix
    foreach my $type (reverse @types) {
			# no dash
      my $candidate_font = $font . $type;
      if (grep { $_ eq $candidate_font } @available_fonts) {
				print STDERR "Debug: font=$candidate_font\n" if($debug);
        return $candidate_font;  # Return the first valid font found
      }
			# with dash
      $candidate_font = $font . "-" . $type;
      if (grep { $_ eq $candidate_font } @available_fonts) {
				print STDERR "Debug: font=$candidate_font\n" if($debug);
        return $candidate_font;  # Return the first valid font found
      }
    }
    return undef;  # No valid font found
  }
}

# Ensure font is valid #####################################
sub test_font {
  my ($font, $iso) = @_;
  my @isofonts = @PostScript_Simple::isofonts;
  my @fonts = @PostScript_Simple::extfonts;

  ####### Check for valid font

  # List fonts
  if ($font eq "list") {
    print "--- Regular ---\n";
    my @fonts_c = collapse_or_find_font("collapse", "", @fonts);  # Collapse all
    for my $f (sort @fonts_c) {
      print $f . "\n";
    }
    print "--- Latin1 compatible ---\n";
    my @isofonts_c = collapse_or_find_font("collapse", "", @isofonts);  # Collapse all
    for my $f (sort @isofonts_c) {
      print $f . "\n";
    }
    exit;
  }

  # random
  if ($font eq "random") {
    if ($iso) {
      my $i = int(rand(scalar @isofonts));
      $font = $isofonts[$i];
    } else {
      my $i = int(rand(scalar @fonts));
      $font = $fonts[$i];
    }
  }

  # make sure font is ok
  if ($iso) {
    if (!grep { $_ eq $font } @isofonts) {
      my $closest_font = collapse_or_find_font("search", $font, @isofonts);
      if ($closest_font) {
        $font = $closest_font;
      } else {
        print STDERR "$0 error: Invalid ISO font: $font\n";
        exit(1);
      }
    }
    $font .= "-iso";
	} else {
    if (!grep { $_ eq $font } (@fonts, @isofonts)) {
      my $closest_font = collapse_or_find_font("search", $font, (@fonts, @isofonts));
      if ($closest_font) {
        $font = $closest_font;
      } else {
        print STDERR "$0 error: Invalid ISO font: $font\n";
        exit(1);
      }
    }
  }
  return $font;
}

# Ensure colours are valid #################################
sub test_colours {
  my($colour, $background) = @_;
  my(@backgrounds, @both);
  my $fh;
  my @colours = keys %PostScript_Simple::pscolours;

  $colour = lc $colour;
  $background = lc $background;
  
  # get colours ######

  # get backgrounds
  open($fh, '<', "$Bin/netpbm_rgb.txt"); 
  @backgrounds = map {/^\s*\d+\s+\d+\s+\d+\s+(\w+)/ ? lc($1) : () } (<$fh>);
  close($fh);
  
  # look for common
  for my $c (@colours) {
    if(grep {lc $_ eq lc $c} @backgrounds) {push(@both, lc $c)}
  }
  
  # list fonts  #######
  if($colour eq "list" or $background eq "list") {
    for my $c (sort @both) {
      print $c . "\n";
    }
    exit;
  }

  # random #######
  if($colour eq "random") {
    my $i = int(rand(scalar @both));
    $colour = $both[$i];
  }
  if($background eq "random") {
    my $i = int(rand(scalar @both));
    $background = $both[$i];
  }

  # check colour
  if($colour ne 'default') {
    if(!grep($_ eq $colour, (@both))) {
      print STDERR "$0 error: Invalid colour: $colour\n";
      exit(1);
    }
	}
  
  # check background
  if($background ne 'transparent') {
    if(!grep($_ eq $background, (@both))) {
      print STDERR "$0 error: Invalid background: $background\n";
      exit(1);
    }
  }

  # make sure not same
  if($colour eq $background) {
    print STDERR "$0 error: colour and background cannot be the same\n";
    exit(1);
  }    
  
  return($colour, $background);
}

# hex48_to_rgb ##########################################

sub hex48_to_rgb {
    my ($hex) = @_;

    # Remove the leading "#" if present
    $hex =~ s/^#//;

    # Extract the first 12 characters (4 hex digits for each colour component)
    my $r = substr($hex, 0, 4);  # Red component
    my $g = substr($hex, 4, 4);  # Green component
    my $b = substr($hex, 8, 4);  # Blue component

    # Convert the 16-bit hex values to decimal (0-65535)
    $r = hex($r);
    $g = hex($g);
    $b = hex($b);

    # Scale 16-bit values (0-65535) down to 8-bit values (0-255)
    $r = int($r / 257);  # 65535 / 257 = 255
    $g = int($g / 257);
    $b = int($b / 257);

    return ($r, $g, $b);
}

# runprog ###################################################

sub runprog {
  my($cmd) = @_;
  
  print STDERR "CMD=$cmd\n" if($debug);
  system("$cmd 2>> $file.log");
  if(-s "$file.log") {
    print STDERR "error: system call failed: $cmd\n";
    system("cat $file.log");
    exit 1;
  }
}

# main ######################################################
sub main {
  # User settable params with default values
  my $ansi       = 0;
  my $colour     = 'default';
  my $background = "transparent";
  my $font       = 'Helvetica';
  my $line       = 1;
  my $preserve   = 0;
  my $rotate     = 0;
  my $size       = '65';
  my $width      = 20;
  # Internal variables
  my $help       = 0;
  my $i          = 0;
  my $iso        = 0;  # Latin1
  my $p;
  my $text       = "";
  my $version    = 0;
  my @text       = ();
	
	my ($term_foreground, $term_background) = test_sixel();

  if(-d "/dev/shm/.") {
    $file       = "/dev/shm/$ENV{USER}/bidet_tmp";
  } else {
    $file       = "/tmp/$ENV{USER}/bidet_tmp";
  }
  mkdir(dirname($file));
  # Get options 
  Getopt::Long::Configure ("bundling");
  GetOptions(
    "ansi|a"         => \$ansi,
    "background|b=s" => \$background,
    "debug|d"        => \$debug,
    "colour|c=s"     => \$colour,
    "font|f=s"       => \$font,  
    "line|l=f"       => \$line,
    "preserve|p"     => \$preserve,
    "rotate|r"       => \$rotate,
    "size|s=i"       => \$size,
    "width|w=i"      => \$width,
    "help|h|?"       => \$help,
    "version|v"      => \$version,
  ) or usage();
  if($help) {usage();}
  if($version) {usage(1);}
  if($font   eq "list") {test_font($font, $iso)}
  if($colour eq "list" or $background eq "list") {test_colours($colour, $background)}

  if(
    (!@ARGV) # and (!test_stdin())
  ) {usage();}  
  $Text::Wrap::columns  = $width;
  
  ####### Get text
  if(@ARGV and $ARGV[0] ne '-') {
    if(@ARGV==1 and -f $ARGV[0]) {
      my $fh;
      
      open($fh, '< :encoding(UTF-8)', $ARGV[0]);
      @text = <$fh>;
      close($fh);
    } else {
      @text = @ARGV;
    }
  } else {
    @text = <STDIN>;
  }
  if(!$preserve) {
    $text = join(" ",@text);
    $text =~ s/\n/ /sg;
    $Text::Wrap::separator="\n";
    $text = wrap("","",$text);
    @text = split(/\n/, $text);
  }
  if(grep(/[\x7f-\xff]/, @text)) {
    $iso = 1;
  }    

  ######### make sure font is valid   
  $font = test_font($font, $iso);

  ######### make sure colours are valid
  ($colour, $background)=test_colours($colour, $background);
  $colour     = $term_foreground unless($colour     ne 'default');
  $background = $term_background unless($background ne 'transparent');
  
  ######## Create PostScript file
  
  # create a new PostScript object
  $p = new PostScript_Simple(
    papersize => "A0",
    colour    => 1,
    eps       => 0,
    units     => "in",
    reencode  => 'ISOLatin1Encoding',  # iso8859-1
  );
   
  # create a new page
  $p->newpage;
  
	# SAMPLE TRICKS
  if(0) { 
    # draw some lines and other shapes
    $p->line(1,1, 1,4);
    $p->linextend(2,4);
    $p->box(1.5,1, 2,3.5);
    $p->circle(2,2, 1);
    $p->setlinewidth( 0.01 );
    $p->curve(1,5, 1,7, 3,7, 3,5);
    $p->curvextend(3,3, 5,3, 5,5);
    # draw a rotated polygon in a different colour
    $p->setcolour(0,100,200);
    $p->polygon({rotate=>45}, 1,1, 1,2, 2,2, 2,1, 1,1);
  }
  
  # add some text
  if(lc($colour) eq 'white') {
    # Can't use true white due to masking
    $colour="snow";
    if(lc($background) eq 'snow') {
      $background='white';
    }
  }
	# hex : #000000000000
	if($colour =~ m/^#[0-9a-f]{12}$/) {
		my($r,$g,$b) = hex48_to_rgb($colour);
    $p->setcolour($r,$g,$b);
	# name : white
	} else {
    $p->setcolour($colour);
	}
  $p->setfont($font, $size);
  $i=scalar(@text) * $line;
  for $text (@text) {
    $p->text(1, $i, $text);
    $i -= $line;
  }
  $p->text(1,$i , " ");
  
  # write the output to a file
  $p->output("$file.ps");
  
  ######## Convert to Sixel and output
  
  # pamflip        Flips images around various ways
  # pampaintspill  smoothly spill colours into the background
  # ppmpat         add pattern to background
  # pnmtile        add tiles to background

  # remove log
  unlink("$file.log");
  # ps -> ppm
  runprog("(gs -sDEVICE=ppmraw -sPAPERSIZE=a0 -sOutputFile=- -sNOPAUSE -q -dBATCH $file.ps | pnmcrop| pnmmargin -white 10 ) > $file.ppm");
  # change background
  runprog("(cat $file.ppm | ppmchange -closeok white '$background' | sponge ${file}.ppm)") unless($background eq 'white');
  # rotate
  if($rotate) {
    # do we have the crappy Debian netpbm?
    my $debian = `type pamcomp 2>/dev/null`;
    if($debian !~ /pamcomp/) {
      print STDERR "Note: You have the lobotomized Debian netpbm. Features are greatly restricted.\n";
    } else {
      runprog("(pnmrotate -background '$background' -90 < ${file}.ppm | sponge ${file}.ppm)");
    } 
  }
  # ppm -> png
  runprog("(cat $file.ppm | pnmtopng ) > $file.png");
  if($ansi) {
    # png -> ans 
    runprog("$Bin/img2ans -b'$term_background' $file.png > $file.ans");
    # output result
    system("cat $file.ans");
  } else {
    # png -> six  (img2sixel does not reliably guess the terminal's bg colour)
    runprog("(cat $file.png | img2sixel -I -B '$term_background') > $file.six");
    # output result
    system("cat $file.six");
  }
  # delete tmp files
  unlink(glob("$file*")) unless($debug);
}

# Call main sub
main();

__END__

################################################################################
DEVELOPER NOTES:

fortune -s | bidet -c random -b random -f random -

Source format choices:
  FMT     PROG         PACKAGE          USE
- ps     (gs)          ghostscript      NO
- pdf    (pdftoppm)    poppler-utils    ?
- latex  (latex2gif)   tth-common       ?
- rtf    (RTF2PNG.EXE) US$79            NO

--------------

The quick brown fox jumps over the lazy dog
Voyez le brick géant que j'examine près du wharf

------------

pAm  ????     ????
pBm  bitmap   b & w
pGm  graymap  gray scale
pNm  N={B,G,P}
pPm  pixmap   colour    ***

-------------

export RGBDEF="/usr/share/netpbm/rgb.txt"  <-- not set in Cygwin by default
sh: 1: pamcomp: not found                  <-- not available on Ubuntu
sh: 1: pnmrotate: not found                <-- not available on Ubuntu

apt files netpbm | egrep  /bin/ | wc -l
365

dpkg -L netpbm  | egrep  /bin/ | wc -l
233

expr 365 - 233
132 *** MISSING! WTF!?

----------

ghostscript/9.52/Resource/Init/FCOfontmap-PCLPS2
ghostscript/9.52/Resource/Init/Fontmap.GS
ghostscript/9.52/Resource/Init/gs_fonts.ps

---------

Port to Tektronix window of xterm?
Port to Linux console (TERM=linux)

---------

#!/bin/bash

# Remove log
rm -f "$file.log"

# Convert PS to PNG and crop
convert -density 300 "$file.ps" -trim +repage -bordercolor white -border 10 "$file.png"

# Change background if not white
if [ "$background" != "white" ]; then
    convert "$file.png" -fuzz 1% -fill "$background" -opaque white "$file.png"
fi

# Rotate if needed
if [ "$rotate" = true ]; then
    convert "$file.png" -background "$background" -rotate 90 "$file.png"
fi

if [ "$ansi" = true ]; then
    # Convert PNG to ANSI
    img2ans -b"$term_background" "$file.png" > "$file.ans"
    # Output result
    cat "$file.ans"
else
    # Convert PNG to Sixel
    img2sixel -I -B "$term_background" "$file.png" > "$file.six"
    # Output result
    cat "$file.six"
fi
