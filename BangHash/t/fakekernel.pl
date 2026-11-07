#!/usr/bin/perl
# fakekernel.pl KERNEL SCRIPT [ARGS...]
#   (The full tool is ../shebanglab; this small shim is what test_configure.sh uses.)
#
# Pretend to be the kernel's #! handler: read the first line of SCRIPT,
#   "#!/path/to/interpreter  args-string"
# and exec the interpreter the way the given kernel would.  The kernels are the
# names used everywhere in this project (config.hh has KERNEL_LINUX etc.):
#
#   linux   : argv = interp, "args-string", script, ARGS     (Linux, Cygwin, FreeBSD)
#   naive   : args-string split on whitespace only; backslashes
#             and quotes are NOT honoured                  (macOS)
#   solaris : only the first word of args-string is passed on;
#             the rest is dropped                          (Solaris)
#
# and one made-up kernel, which no known system is, so configure's handling of it can be tested:
#
#   perfect : args-string split like a shell: backslashes and
#             quotes honoured (configure treats it as kernel 1)
#   weird   : passes the string back to front and then a stray word: nothing configure recognises
#             (it warns and uses the naive kernel)
#
# Any kernel can have a limit on the length of the #! line, written KERNEL:N or KERNEL:rN.
# With :N the kernel cuts the line off after N bytes (as Linux does: 127 before 5.1, 255 since);
# with :rN it refuses to run a script whose line is longer than N (no exec at all).
#
# Then argv = interp, <split args>..., script, ARGS
#
# Use: lets us test env2 against each kind of kernel on a machine that only
# has one.  Build env2 for the matching kernel.
use strict; use warnings;
use Text::ParseWords qw(shellwords);

my ($mode, $script, @user) = @ARGV;
die "usage: $0 linux|naive|solaris|perfect|weird[:N|:rN] script [args]\n" unless defined $script;
my ($limit, $refuse);
if ($mode =~ s/:(r?)(\d+)$//) { ($refuse, $limit) = ($1, $2) }
open(my $fh, '<', $script) or die "$script: $!\n";
my $line = <$fh>; close $fh;
chomp $line;
if (defined $limit && length($line) > $limit) {
  exit 126 if $refuse;                     # the kernel will not run it
  $line = substr($line, 0, $limit);        # or it cuts the line short
}
$line =~ s/^#!\s*// or die "$script: no #! line\n";
my ($interp, $rest) = split(/\s+/, $line, 2);
$rest = '' unless defined $rest;

my @args;
if    ($mode eq 'linux')   { @args = length($rest) ? ($rest) : () }
elsif ($mode eq 'naive')   { @args = split(' ', $rest) }
elsif ($mode eq 'perfect') { @args = shellwords($rest) }
elsif ($mode eq 'weird')   { @args = (scalar reverse($rest), 'x') }
elsif ($mode eq 'solaris') { my @w = split(' ', $rest); @args = @w ? ($w[0]) : () }
else { die "unknown mode '$mode'\n" }

exec { $interp } $interp, @args, $script, @user or die "exec $interp: $!\n";
