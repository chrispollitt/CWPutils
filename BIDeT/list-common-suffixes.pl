#!/usr/bin/perl
use strict;
use warnings;
use File::Slurper 'read_lines';

# Sample list of Type1 PS fonts (you can replace this with your actual list)
my @standard = qw(
  Black
  Bold
  Compressed
  Condensed
  Heavy
  Italic
  Light
  Medium
  Oblique
  Regular
);
# list of Type1 PS fonts
my @font_list = read_lines('fontlist.txt');

# Hash to store suffix frequencies
my %suffix_count;

# Collect all suffixes of length 3 or more from each font name
foreach my $font (@font_list) {
  # Starting from length 3 to the full length of the font name
  for my $i (3 .. length($font)) {
    my $suffix = substr($font, -$i);
    $suffix_count{$suffix}++
    if(
      $suffix =~ /^-[a-z]/i # must start with dash
    );
  }
}

# Now we need to filter out the longest repeating suffixes
my %valid_suffixes;

# First, gather all suffixes that appear at least 2 times
foreach my $suffix (keys %suffix_count) {
  if (
    ($suffix_count{$suffix} >= 2) or    # 2+ reps
    (grep {$suffix =~ /$_/} @standard)  # standard suffix string
  ) {
    $valid_suffixes{$suffix} = $suffix_count{$suffix};
  }
}

# Now, eliminate shorter suffixes that are part of a longer suffix
my %longest_suffixes;
if(0) {
  foreach my $suffix (sort { length($b) <=> length($a) } keys %valid_suffixes) {
    my $is_part_of_longer = 0;
    foreach my $long_suffix (keys %longest_suffixes) {
      if ($long_suffix =~ /\Q$suffix\E$/) {
        $is_part_of_longer = 1;
        last;
      }
    }
    # If not part of a longer suffix, add it to longest_suffixes
    unless ($is_part_of_longer) {
      $longest_suffixes{$suffix} = $valid_suffixes{$suffix};
    }
  }
} else {
	%longest_suffixes = %valid_suffixes;
}

# Print the results
foreach my $suffix (sort { length($b) <=> length($a) } keys %longest_suffixes) {
  print "$suffix\n";
}
foreach my $suffix (@standard) {
  print "$suffix\n"; # no dash required
}
