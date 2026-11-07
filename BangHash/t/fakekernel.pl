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
#
# Then argv = interp, <split args>..., script, ARGS
#
# Use: lets us test env2 against each kind of kernel on a machine that only
# has one.  Build env2 for the matching kernel.
use strict; use warnings;
use Text::ParseWords qw(shellwords);

my ($mode, $script, @user) = @ARGV;
die "usage: $0 linux|naive|solaris|perfect script [args]\n" unless defined $script;
open(my $fh, '<', $script) or die "$script: $!\n";
my $line = <$fh>; close $fh;
chomp $line;
$line =~ s/^#!\s*// or die "$script: no #! line\n";
my ($interp, $rest) = split(/\s+/, $line, 2);
$rest = '' unless defined $rest;

my @args;
if    ($mode eq 'linux')   { @args = length($rest) ? ($rest) : () }
elsif ($mode eq 'naive')   { @args = split(' ', $rest) }
elsif ($mode eq 'perfect') { @args = shellwords($rest) }
elsif ($mode eq 'solaris') { my @w = split(' ', $rest); @args = @w ? ($w[0]) : () }
else { die "unknown mode '$mode'\n" }

exec { $interp } $interp, @args, $script, @user or die "exec $interp: $!\n";
