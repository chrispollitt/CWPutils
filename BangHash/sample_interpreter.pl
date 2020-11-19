#!/usr/bin/perl -w
#
# This interpreter is silly and should be deleted.
#      

use strict;
use warnings;

sub usage {
  print "Usage: $0 [<iflags>] <script> [<sflags>] [<sargs>]\n";
  exit(1);
}

sub parse_flags {
  my($iargs, $sargs) = @_;
  my @sargs_t;
  my %flags;
  my $farg=undef;
  my $delim=0;
  my $oc;
  my $ia;
  
  # NOTE: This does not handle quoted or escaped whitespaces
  $ia = shift @$iargs;
A:for my $a (@$iargs) {
B:  for my $b (split /\s+/, $a) {
      if($b eq "~~") {
        $delim=1;
      } elsif ($delim) {
        push(@sargs_t, $b);
      } elsif ($b =~ s/^-//) {
        $farg= undef;
        $oc  = undef;
C:      for my $c (split //, $b) {
          if($c =~ /[:=]/) {
            $farg=$oc;
            $flags{$farg} = "";
          } else {
            if(defined $farg) {
              $flags{$farg} .= $c;
            } else {
              $flags{$c} = 1;
            }
          }
        } continue {
          $oc = $c;
        }
      } else {
        last A;
      }
    }
  }
  unshift @$iargs, $ia;
  splice(@$sargs, 1, 0, @sargs_t);
  # print found flags #####
  print "---my flags---\n";
  for my $f (sort keys %flags) {
    print "$f='$flags{$f}'\n";
  }
}

sub print_args {
  # vars
  my @pargs; # Perl args        (super interpreter)
  my @iargs; # Interpreter agrs (this program)
  my @sargs; # Script args      (child to be run)
  my $i;
  my $found;
  my $fh;
  my $line;
  local $" = " ";
  # get perl args ############################
  push(@pargs, $^X);
  if(-d "/proc" and -f "/proc/self/cmdline") {
    open($fh, "<", "/proc/self/cmdline");
    $line = <$fh>;
    close($fh);
    $line =~ s/\c@/\cj/g;
  } else {
    $line = (`ps -p $$ -o command=`)[0];
    $line =~ s/ /\cj/g;
  }
  $i = 1;
  $found=0;
  for my $a (split /\cj/, $line) {
    if($a =~ /^-/) {
      if($found>1) {
        1;
      } else {
        push(@pargs, $a);
      } 
    } else {
      $found++;
    }
  }
  # get inter args ###########################
  push(@iargs, $0);
  $i = 1;
  $found=0;
  for my $a (@ARGV) {
    if($a =~ /^[-~]/) {
      if($found) {
        push(@sargs, $a);
      } else {
        push(@iargs, $a);
      } 
    } else {
      $found++;
      push(@sargs, $a);
    }
  }
  # print #####
  print "---perl args---\n";
  for $i (0..$#pargs) { print "argv[$i]=$pargs[$i]\n"; }
  print "---inter args---\n";
  for $i (0..$#iargs) { print "argv[$i]=$iargs[$i]\n"; }
  print "---script args---\n";
  for $i (0..$#sargs) { print "argv[$i]=$sargs[$i]\n"; }

  return(\@iargs, \@sargs);
}

sub call_bash {
  my($iargs, $sargs) = @_;
  my $fh;
  my @lines;
  my $sa;
  local $" = "' '";

  # exists?  
  if(! -f $$sargs[0]) {
    print "error: script not found: $$sargs[0]\n";
    return(1);
  }
  # read in
  open($fh, "<", $$sargs[0]);
  @lines = <$fh>;
  close($fh);
  # exec
  open($fh, "|-", "/bin/bash --norc --noprofile -s");
  # set vars
  print $fh "typeset -a argv=('@$iargs')\n";
  print $fh "BASH_ARGV0=$$sargs[0]\n";
  $sa = shift @$sargs;
  print $fh "set -- '@$sargs'\n";
  unshift @$sargs, $sa;
  # run script
  for my $line (@lines) {
    print $fh $line;
  }
  close($fh);
}

sub main {
  #### vars
  my $iargs;
  my $sargs;
  #### Usage
  if(!@ARGV) {
    usage();
  }
  #### Print my args
  ($iargs, $sargs) = print_args();
  #### Parse flags
  parse_flags($iargs, $sargs); # iargs=in sargs=in+out
  #### Execute script
  call_bash($iargs, $sargs);
}
main();
