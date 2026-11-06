#!/usr/bin/perl
# t/splitcompare.pl HARNESS FLAGS MAXLEN
#   (run by make test with FLAGS="" ; see also DEVELOPER_NOTES.txt)
# Generate every string over a small alphabet up to MAXLEN, split each with
# env2 (via HARNESS) and with a reference, and report where they disagree.
#
# FLAGS (passed to the harness, same letters as env2):
#   none, or "S": env2's default splitter, the shellwords port.  Reference: Perl's
#     shellwords().  They must agree on every string, so this is STRICT: any
#     disagreement makes the script exit 1.
#   "W": env2's wordexp mode.  Reference: a real POSIX sh (eval "set -- $string").
#     Also STRICT.  (The corpus has none of the characters sh treats specially except
#     quotes and backslash.)
#   "C", or any of s, p, x (which imply it): the classic split_classic().  Reference:
#     Perl's shellwords().  Use FLAGS "Csp": without s it keeps every backslash, so
#     nearly every string with one differs and shows as UNEXPLAINED.  With "s", the
#     known differences A, B and C below account for everything, plus the "perl:
#     unmatched quote, env2: accepts" class (a quote with nothing after it).
#     ("L" is the old name of "C".)
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

# wordexp mode is checked against a real POSIX sh instead of Perl
my @sh_out;
my $use_sh = ($flags =~ /W/);
if ($use_sh) {
  my $script = "/tmp/splitcmp.$$.sh";
  open(my $sf, '>', $script) or die;
  print $sf <<'SH';
while IFS= read -r line; do
  out=$( ( eval "set -- $line" || exit 1; printf U; for a in "$@"; do printf '\037%s' "$a"; done ) 2>/dev/null )
  if [ $? -eq 0 ]; then printf '%s\n' "$out"; else printf 'M\n'; fi
done
SH
  close $sf;
  my $in2 = "/tmp/splitcmp.$$.in2";
  open(my $fh2, '>', $in2) or die; print $fh2 "$_\n" for @corpus; close $fh2;
  @sh_out = `/bin/sh $script < $in2`;
  unlink $script, $in2;
  die "sh gave ", scalar(@sh_out), " lines for ", scalar(@corpus), " inputs\n" unless @sh_out == @corpus;
}

my (%count, %examples);
for my $i (0 .. $#corpus) {
  my $s = $corpus[$i];
  chomp(my $o = $ours[$i]);
  my ($flag, @ot) = split /\x1f/, $o, -1;
  @ot = () if @ot == 1 && $ot[0] eq '' && $o eq "${flag}";   # no tokens
  shift @ot while @ot && $ot[0] eq '' && 0;

  my (@pt, $p_unmatched);
  if ($use_sh) {
    chomp(my $r = $sh_out[$i]);
    my ($rf, @rt) = split /\x1f/, $r, -1;
    @pt = @rt;
    $p_unmatched = ($rf eq 'M') ? 1 : 0;
  } else {
    @pt = shellwords($s);
    $p_unmatched = (!@pt && $s =~ /\S/) ? 1 : 0;
  }
  my $o_unmatched = $flag eq 'M' ? 1 : 0;

  my $class;
  if ($p_unmatched || $o_unmatched) {
    if ($p_unmatched && $o_unmatched) { $class = 'both: unmatched quote' }
    elsif ($p_unmatched)              { $class = 'perl: unmatched quote, env2: accepts' }
    # known wordexp library quirk: glibc's wordexp() rejects a backslash at the very end
    #   of the string, where sh keeps it as a literal backslash
    elsif ($use_sh && $s =~ /\\\z/)   { $class = 'library quirk: trailing backslash is an error (glibc wordexp)' }
    else                              { $class = 'env2: unmatched quote, perl: accepts' }
  } else {
    my $same = (@ot == @pt) && !grep { $ot[$_] ne $pt[$_] } 0 .. $#pt;
    if    ($same) { $class = 'same' }
    # known wordexp library quirk: glibc's wordexp() returns an extra empty word when an
    #   empty pair of quotes touches other text (""a gives "" and a; sh gives just a)
    elsif ($use_sh && $s =~ /(""|'')/) { $class = 'library quirk: empty quotes next to text give an extra empty word (glibc wordexp)' }
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

# strict mode (shellwords and wordexp): nothing but "same" and "both: unmatched quote" is
# allowed.  The one exception: the known quirks of the C library's wordexp() (see above),
# which are reported but do not fail the check; anything else does.
my $classic = ($flags =~ /[CLspx]/) && ($flags !~ /[SW]/);   # same rule as env2 and the harness
if (!$classic) {
  my @bad = grep { $_ ne 'same' && $_ ne 'both: unmatched quote' && $_ !~ /^library quirk:/ } keys %count;
  if (@bad) { print "\nFAIL: the splitter disagrees with its reference (Perl for shellwords, sh for wordexp)\n"; exit 1 }
  my @quirks = grep { /^library quirk:/ } keys %count;
  if (@quirks) {
    print "\nOK: the splitter agrees with its reference on every string except the known library quirks above\n";
  } else {
    print "\nOK: the splitter agrees with its reference on every string\n";
  }
}
