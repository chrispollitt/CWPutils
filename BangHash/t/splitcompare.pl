#!/usr/bin/perl
# t/splitcompare.pl HARNESS FLAGS MAXLEN
#   (run by make test with FLAGS=S; see also DEVELOPER_NOTES.txt)
# Generate every string over a small alphabet up to MAXLEN, split each with
# env2 (via HARNESS) and with Perl's shellwords(), and report where they disagree.
#
# FLAGS "S": env2's shellwords port.  It must agree with Perl on every string,
#   so this is STRICT: any disagreement makes the script exit 1.
# Otherwise: env2's original split_string().  Use FLAGS containing "s" (e.g. "sp"):
#   without -s it keeps every backslash, so nearly every string with one differs
#   and shows as UNEXPLAINED.  With "s", the known differences A, B and C below
#   account for everything, plus the "perl: unmatched quote, env2: accepts" class
#   (a quote with nothing after it).
use strict; use warnings;
use Text::ParseWords qw(shellwords);

my ($harness, $flags, $maxlen) = @ARGV;
$maxlen //= 6;
my @alpha = ('a', 'b', ' ', "\t", "'", '"', '\\');
# SPLITCMP_WS=1: other whitespace instead (Perl's \s also has CR, FF and VT)
@alpha = ('a', ' ', "\r", "\f", "\x0b", "'", '"', '\\') if $ENV{SPLITCMP_WS};

# all strings up to maxlen
my @corpus = ('');
my @level  = ('');
for my $len (1 .. $maxlen) {
  my @next;
  for my $s (@level) { push @next, $s . $_ for @alpha }
  push @corpus, @next;
  @level = @next;
}

# run env2's splitter on the whole corpus in one process
my $in = "/tmp/splitcmp.$$.in";
open(my $fh, '>', $in) or die; print $fh "$_\n" for @corpus; close $fh;
my @ours = `$harness $flags < $in`;
unlink $in;
die "harness gave ", scalar(@ours), " lines for ", scalar(@corpus), " inputs\n" unless @ours == @corpus;

my (%count, %examples);
for my $i (0 .. $#corpus) {
  my $s = $corpus[$i];
  chomp(my $o = $ours[$i]);
  my ($flag, @ot) = split /\x1f/, $o, -1;
  @ot = () if @ot == 1 && $ot[0] eq '' && $o eq "${flag}";   # no tokens
  shift @ot while @ot && $ot[0] eq '' && 0;

  my @pt = shellwords($s);
  my $p_unmatched = (!@pt && $s =~ /\S/) ? 1 : 0;
  my $o_unmatched = $flag eq 'M' ? 1 : 0;

  my $class;
  if ($p_unmatched || $o_unmatched) {
    if ($p_unmatched && $o_unmatched) { $class = 'both: unmatched quote' }
    elsif ($p_unmatched)              { $class = 'perl: unmatched quote, env2: accepts' }
    else                              { $class = 'env2: unmatched quote, perl: accepts' }
  } else {
    my $same = (@ot == @pt) && !grep { $ot[$_] ne $pt[$_] } 0 .. $#pt;
    if    ($same) { $class = 'same' }
    # known difference A: -s keeps a backslash that is in front of whitespace or a quote
    elsif ($s =~ /\\[ \t'"]/) { $class = 'diff A: backslash before space/tab/quote kept' }
    # known difference B: empty quote pairs are dropped (without -p), or make an extra
    #   empty arg when next to text (with -p); shellwords() keeps "" as an empty arg
    elsif ($s =~ /(""|'')/)   { $class = 'diff B: empty quotes' }
    # known difference C: -s strips backslashes inside single quotes too
    elsif ($s =~ /'[^']*\\[^']*'/) { $class = 'diff C: backslash inside single quotes stripped (-s only)' }
    # anything else is new and worth a look
    else                      { $class = 'UNEXPLAINED' }
  }
  $count{$class}++;
  if ($class ne 'same' && $class ne 'both: unmatched quote') {
    my $ex = sprintf("%-14s env2=[%s] perl=[%s]", _vis($s), join('|', map { _vis($_) } @ot), join('|', map { _vis($_) } @pt));
    push @{$examples{$class}}, [length($s), $ex];
  }
}

sub _vis { my $x = shift; $x =~ s/\t/\\t/g; return "<$x>" }

printf "flags='%s' maxlen=%d inputs=%d\n", $flags, $maxlen, scalar(@corpus);
printf "  %-48s %d\n", $_, $count{$_} for sort keys %count;
for my $class (sort keys %examples) {
  my @e = sort { $a->[0] <=> $b->[0] or $a->[1] cmp $b->[1] } @{$examples{$class}};
  print "\n== $class (shortest examples)\n";
  print "  $_->[1]\n" for @e[0 .. ($#e < 14 ? $#e : 14)];
}

# strict mode (the shellwords port): nothing but "same" and "both: unmatched quote" is allowed
if (index($flags, 'S') >= 0) {
  my @bad = grep { $_ ne 'same' && $_ ne 'both: unmatched quote' } keys %count;
  if (@bad) { print "\nFAIL: the shellwords port disagrees with Perl\n"; exit 1 }
  print "\nOK: the shellwords port agrees with Perl on every string\n";
}
