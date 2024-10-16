#!/usr/bin/env perl

use File::Slurper qw~read_lines write_text~;
use Getopt::Long;
use File::Copy qw~copy~;

use strict;
use warnings;

# Command-line options
our $debug   = 0;
our $dry_run = 0;
our $backup  = 0;
our $help    = 0;

# ext           hbang        ver  
our %exts = (
  awk     => [ 'awk'       , '--version' ],
  clj     => [ 'clojure'   , '--version' ],
  erl     => [ 'erlang'    , '--version' ],
  ex      => [ 'elixir'    , '--version' ],
  fish    => [ 'fish'      , '--version' ],
  go      => [ 'go'        , 'version'   ],
  groovy  => [ 'groovy'    , '--version' ],
  hs      => [ 'haskell'   , '--version' ],
  js      => [ 'node'      , '--version' ],
  kts     => [ 'kotlin'    , '--version' ],
  lua     => [ 'lua'       , '-v'        ],
  'm'     => [ 'MATLAB'    , '--version' ],
  php     => [ 'php'       , '--version' ],
  pl      => [ 'perl'      , '--version' ],
  ps1     => [ 'pwsh'      , '--version' ],
  py      => [ 'python3'   , '--version' ],
  R       => [ 'Rscript'   , '--version' ],
  raku    => [ 'raku'      , '--version' ],
  rb      => [ 'ruby'      , '--version' ],
  scala   => [ 'scala'     , '--version' ],
  scm     => [ 'scheme'    , '--version' ],
  sed     => [ 'sed'       , '--version' ],
  sh      => [ 'bash'      , '--version' ],
  st      => [ 'smalltalk' , '--version' ],
  swift   => [ 'swift'     , '--version' ],
  zsh     => [ 'zsh'       , '--version' ],

  true     => [ 'true'       , '--xxx' ],  # xxx
  false    => [ 'false'      , '--xxx' ],  # xxx
);
our %hbangs = swap_hash(%exts);

# swap hash
sub swap_hash {
  my %original_hash = @_;
  my %swapped_hash;

  while (my ($key, $value) = each %original_hash) {
    $swapped_hash{$value->[0]} = $key;
  }

  return %swapped_hash;
}

# Check if the hashbang line contains multiple arguments and suggest using env2
sub check_hashbang {
  my ($hashbang) = @_;
  if ($hashbang =~ m/^#!\s*(\S+)\s+(.+)/) {
    my $interpreter = $1;
    my $arguments = $2;
    print "Hashbang contains multiple arguments: $hashbang\n";
    print "Consider using: #!/usr/bin/env2 $interpreter $arguments\n";
  }
}

# which -a
sub which_a {
  my $cmd = shift or die "Usage: which_a(command)\n";
  my @paths = split /:/, $ENV{PATH};
  my @results;
	
  foreach my $path (@paths) {
    my $full_path = "$path/$cmd";
    if (-x $full_path) {
      push @results, $full_path;
    }
  }
  return @results;
}

# sort ver numbers
sub sort_versions {
  my @versions = @_;
  my @sorted = sort {
    my @a_parts = split /\./, $a;
    my @b_parts = split /\./, $b;
    
    # Remove any non-numeric characters from the parts
    @a_parts = map { s/\D.*//r } @a_parts;
    @b_parts = map { s/\D.*//r } @b_parts;
    
    # Ensure each version has exactly 3 parts by padding with zeros
    push @a_parts, 0 while @a_parts < 3;
    push @b_parts, 0 while @b_parts < 3;
    
    # do the compare
    $a_parts[0] <=> $b_parts[0] ||
    $a_parts[1] <=> $b_parts[1] ||
    $a_parts[2] <=> $b_parts[2]
  } @versions;
  return @sorted;
}

# get latest version
sub get_latest {
	my($hbang, $file, $ext) = @_;
	my(@locs, $verflag, $ver, %vers, $choice);
  # look for interpreter in PATH
  @locs = which_a($hbang);
  if(!@locs) {
  		warn "Unable to locate interpreter in the PATH: $file\n";
  		return;
  }
  # look for ext in hash
  if(exists $exts{$ext}) {
    $verflag = $exts{$ext}->[1];
  } else {
  	warn "Unknown ext for file: $file - '$ext'\n";
  	return;
  }
  # one or many?
  if (@locs == 1) {
  	$choice = $locs[0];	
  } else {
    # loop over locations
    for my $loc (@locs) {
    	$loc =~ s~[\r\n]+$~~;
  		# get version
    	$ver = (grep(/\d\.\d/, `"$loc" $verflag 2>/dev/null`))[0] or $ver = '';
    	$ver =~ s~^.*?(\d(?:\.\d+)+).*[\r\n]+$~$1~ or $ver = 'UNKNOWN';
      warn "DEBUG:   l=$loc v=$ver\n" if($debug);
    	next if($ver eq 'UNKNOWN');
    	$vers{$ver} = $loc;
    }
		# no vers avail
    if(!keys %vers) {
			warn "None of the interpreters returned a version string\n";
			return;
		}
    # sort and loop over versions found
    my @vers = sort_versions(keys %vers);
    for my $ver (@vers) {
    	warn "DEBUG: $vers{$ver} = $ver\n" if($debug);
    }
    # chose most recent version
    $choice = $vers[-1];
    $choice = $vers{$choice};
  }
  return $choice;
}

# Read and update hashbang if needed
sub process_file {
  my($file) = @_;
  my($ext, $hbang, $eol, $ehbang);
	# see if file exists
	if(! -f $file) {
    warn "Unable to find file: $file\n";
    return;
	}
  my @script = read_lines($file);
  my $ohbang = $script[0];
  chomp($ohbang);

  # Backup the original file if needed
  if ($backup) {
    my $backup_file = $file . ".bak";
    copy($file, $backup_file) or warn "Failed to create backup: $backup_file\n";
    print "Backup created: $backup_file\n" if $debug;
  }
	
  # get extension
  $ext = ($file =~ /\.(\w+)$/)[0] or $ext = '';
  # get hashbang
  $hbang = $ohbang;
  $eol = "\n";
  if($hbang =~ m~^#!/?(?:[^/]+/){0,}(?:env2?\s+)?(\w+)(\s+.*)?$~) {
    ($hbang, $ehbang) = ($1, $2 || '');
	} else {
    ($hbang, $ehbang) = ('', '');
	}
	# set hbang if missing
  if(! $hbang) {
  	if($ext) {
  		if(exists $exts{$ext}) {
        $hbang = $exts{$ext}->[0];
  		} else {
  		  warn "Unknown ext for file: $file - '$ext'\n";
  		  return;
  		}
  	} else {
  		warn "Unable to determine script type: $file\n";
  		return;
  	}
  }
  # set ext if missing
  if(! $ext) {
  	if(exists $hbangs{$hbang}) {
  	  $ext = $hbangs{$hbang};
  	} else {
  		warn "Unknown hbang in file: $file - '$hbang'\n";
  		return;
  	}
  }
	# see if ext and interpreter match
	if($ext ne $hbangs{$hbang}) {
		warn("Warning: ext and interpreter do not match!\n");
	}
  # debug out
  warn "DEBUG: f=$file e=$ext h=$hbang\n" if($debug);
	my $choice = get_latest($hbang, $file, $ext);
	return if(!$choice);
  # fix hbang line
  $hbang = "#!" . $choice . $ehbang;
  if($ohbang =~ m~^#!~) {
  	$script[0] = $hbang;
  } else {
  	unshift(@script, $hbang)
  }
  # In dry run mode, don't modify the file
  if ($dry_run) {
    print "Dry run: Would update $file\n" if $debug;
  } else {
    write_text($file, join($eol, @script) . $eol);
	}
  print "f=$file i=$choice\n";
  # Check the hashbang line for multiple args
  if ($hbang =~ /^#!/) {
    check_hashbang($hbang);
  }
}

# Main function
sub main {
	# Disable buffering
  $| = 1;
  select(STDERR); $| = 1; select(STDOUT);
	# parse flags
  GetOptions(
    'debug'    => \$debug,
    'dry-run'  => \$dry_run,
    'backup'   => \$backup,
    'help'     => \$help,
  ) or die "Invalid options. Use --help for usage.\n";
  # show help
  if ($help) {
    print "Usage: $0 [options] <file1> <file2> ...\n";
    print "Options:\n";
    print "  --debug      Enable debug mode\n";
    print "  --dry-run    Show changes without modifying files\n";
    print "  --backup     Create a backup of the original file\n";
    print "  --help       Show this help message\n";
    exit 0;
  }
  # check for files
  my @files = @ARGV;
  if (!@files) {
    die "No files specified. Use --help for usage.\n";
  }
  # loop over files
  foreach my $file (@files) {
    process_file($file);
  }
}

# call main
main();

__END__
