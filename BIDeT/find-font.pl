#!/usr/bin/perl
use strict;
use warnings;

use File::Slurper 'read_lines';

our $debug = 0;

# Define the font list
our @fonts = read_lines('/usr/local/share/BIDeT/fontlist.txt');

# Define style aliases to handle variations (e.g., Italic can be Ital, Oblique, etc.)
our %style_data = (
    regular  => { priority => 1, aliases => ['regular', 'regu', 'roman', 'roma'] },
    italic   => { priority => 2, aliases => ['italic', 'ital', 'oblique', 'obli'] },
    bold     => { priority => 3, aliases => ['bold'] },
    light    => { priority => 4, aliases => ['light', 'ligh'] },
    semilight=> { priority => 4, aliases => ['semilight'] },
    black    => { priority => 5, aliases => ['black'] },
    extended => { priority => 6, aliases => ['extended', 'exte'] },
    demi     => { priority => 7, aliases => ['demi'] },
    medium   => { priority => 7, aliases => ['medium', 'medi'] },
    heavy    => { priority => 8, aliases => ['heavy'] },
    # Add more styles as needed
);
# $style_data{$style_name}{aliases}
# $style_data{$style_name}{priority}

# Function to normalize style names based on aliases
sub normalize_style {
    my ($style) = @_;
    print "DEBUG: Normalizing style: $style\n"  if($debug);
    foreach my $canonical_style (keys %style_data) {
        foreach my $alias (@{$style_data{$canonical_style}{aliases}}) {
            if (lc($style) eq lc($alias)) {
                print "DEBUG: Normalized $style to $canonical_style\n"  if($debug);
                return $canonical_style;
            }
        }
    }
    print "DEBUG: No normalization for $style, returning as is\n"  if($debug);
    return lc($style);  # If no alias found, return the style as lowercase
}

# Function to extract styles from a font name
sub extract_styles {
    my ($font_name, $base_name) = @_;
    print "DEBUG: Extracting styles from: $font_name\n"  if($debug);
    my @extracted_styles;
    
    # Remove the base name
    $font_name =~ s/^$base_name-?//i;
    print "DEBUG: After base name removal: $font_name\n"  if($debug);
    
    # Split the remaining string into potential styles
    my @potential_styles = split(/(?=[A-Z])|-/, $font_name);
    
    foreach my $style (@potential_styles) {
        next if $style eq '';
        my $normalized = normalize_style($style);
        push @extracted_styles, $normalized;
    }
    
    print "DEBUG: Extracted styles: " . join(", ", @extracted_styles) . "\n"  if($debug);
    return @extracted_styles;
}

# Function to calculate style priority score
sub calculate_priority_score {
    my (@styles) = @_;
    my $score = 0;
    foreach my $style (@styles) {
        $score += $style_data{$style}{priority} // 0;
    }
    return $score;
}

# Function to find the matching font
sub find_font {
    my ($base_name, @desired_styles) = @_;
    
    print "DEBUG: Searching for base name: $base_name\n"  if($debug);
    print "DEBUG: Desired styles: " . join(", ", @desired_styles) . "\n"  if($debug);
    
    # Normalize the desired styles based on aliases
    my @normalized_styles = map { normalize_style($_) } @desired_styles;
    print "DEBUG: Normalized desired styles: " . join(", ", @normalized_styles) . "\n"  if($debug);
    
    # Create a regex pattern to match the base name
    my $base_pattern = qr/^$base_name(?:[-]|$)/i;
    
    my @matches;
    
    # Look through the fonts and find potential matches
    for my $font (@fonts) {
        print "DEBUG: Checking font: $font\n"  if($debug);
        if ($font =~ $base_pattern) {
            print "DEBUG: Base name match found\n"  if($debug);
            my @font_styles = extract_styles($font, $base_name);
            
            # Check if all desired styles are present in the font name
            my $match = 1;
            foreach my $desired_style (@normalized_styles) {
                if (!grep { $_ eq $desired_style } @font_styles) {
                    $match = 0;
                    print "DEBUG: Missing style: $desired_style\n"  if($debug);
                    last;
                }
            }
            
            if ($match) {
                push @matches, {
                    name => $font,
                    styles => \@font_styles,
                    priority_score => calculate_priority_score(@font_styles)
                };
                print "DEBUG: Match found: $font (Priority score: " . calculate_priority_score(@font_styles) . ")\n"  if($debug);
            }
        }
    }
    
    # Sort matches by priority score (lower is better) and then by number of styles (fewer is better)
    @matches = sort { 
        $a->{priority_score} <=> $b->{priority_score} || 
        scalar(@{$a->{styles}}) <=> scalar(@{$b->{styles}})
    } @matches;
    
    print "DEBUG: All matches: " . join(", ", map { $_->{name} } @matches) . "\n"; # if($debug);
    
    return @matches ? $matches[0]->{name} : undef;  # Return the best match or undef if no match
}

# Main program
my $base_font = "URWGothic"; # "NimbusSansNarrow";
chomp($base_font);
my $style_input = "Italic";
chomp($style_input);
my @styles = split(/\s+/, $style_input);

print "DEBUG: Input base font: $base_font\n"  if($debug);
print "DEBUG: Input styles: " . join(", ", @styles) . "\n"  if($debug);

# Find and print the matching font
my $matching_font = find_font($base_font, @styles);
if ($matching_font) {
    print "Matching font: $matching_font\n";
} else {
    print "No matching font found.\n";
}