/*
 * cut2 - An improved version of GNU cut with proper quoting and PCRE delimiter handling.
 *
 * Licensed under the MIT License (see LICENSE file for details).
 * (c) 2025 OpenAI
 */
 
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <getopt.h>
#include <pcre.h>

#define MAX_FIELDS 100
#define MAX_LINE_LENGTH 8192
#define DEFAULT_DELIMITER "[\t ]+"

typedef struct {
    int type;         // 1 = field mode (-f), 2 = character mode (-c)
    int fields[MAX_FIELDS];
    int field_count;
    char *delimiter_pattern;
    pcre *delimiter_regex;
    pcre_extra *delimiter_extra;
} CutOptions;

void usage() {
    fprintf(stderr, "Usage: cut2 [-f LIST | -c LIST] [-d DELIM] [FILE...]\n");
    fprintf(stderr, "  -f LIST    Select fields (comma-separated, supports ranges)\n");
    fprintf(stderr, "  -c LIST    Select characters (comma-separated, supports ranges)\n");
    fprintf(stderr, "  -d DELIM   Field delimiter PCRE pattern (default: [\\t ]+)\n");
    exit(1);
}

// Parse field/character list (supports ranges like 1-3,4,5-)
void parse_list(char *list, int *array, int *count) {
    char *token = strtok(list, ",");
    while (token && *count < MAX_FIELDS) {
        if (strchr(token, '-')) {  // Handle ranges like 2-5
            int start, end;
            if (sscanf(token, "%d-%d", &start, &end) == 2) {
                for (int i = start; i <= end && *count < MAX_FIELDS; i++) {
                    array[(*count)++] = i;
                }
            } else if (sscanf(token, "%d-", &start) == 1) { // Open-ended range 3-
                for (int i = start; i < MAX_FIELDS; i++) {
                    array[(*count)++] = i;
                }
            }
        } else {  // Single values
            array[(*count)++] = atoi(token);
        }
        token = strtok(NULL, ",");
    }
}

// Compile PCRE pattern
int compile_delimiter(CutOptions *options) {
    const char *error;
    int erroffset;
    
    options->delimiter_regex = pcre_compile(
        options->delimiter_pattern,
        0,                    // No special options
        &error,
        &erroffset,
        NULL
    );
    
    if (!options->delimiter_regex) {
        fprintf(stderr, "PCRE compilation failed at offset %d: %s\n", erroffset, error);
        return -1;
    }
    
    options->delimiter_extra = pcre_study(options->delimiter_regex, 0, &error);
    
    return 0;
}

// Split line using PCRE while respecting quotes
int split_fields_regex(char *line, CutOptions *options, char *fields[], int max_fields) {
    int count = 0;
    char *ptr = line;
    int in_quotes = 0;
    char quote_char = 0;
    
    // First field always starts at the beginning
    fields[count++] = ptr;
    
    int ovector[30];
    int line_len = strlen(line);
    int offset = 0;
    
    while (offset < line_len && count < max_fields) {
        // Check if we're in a quoted section
        if (!in_quotes && (line[offset] == '"' || line[offset] == '\'')) {
            in_quotes = 1;
            quote_char = line[offset];
        } else if (in_quotes && line[offset] == quote_char && (offset == 0 || line[offset-1] != '\\')) {
            in_quotes = 0;
            quote_char = 0;
        }
        
        // Only match delimiter if not in quotes
        if (!in_quotes) {
            int rc = pcre_exec(
                options->delimiter_regex,
                options->delimiter_extra,
                line,
                line_len,
                offset,
                0,
                ovector,
                30
            );
            
            if (rc >= 0 && ovector[0] == offset) {
                // Found delimiter at current position
                // Null-terminate current field
                line[ovector[0]] = '\0';
                
                // Start next field after delimiter
                offset = ovector[1];
                if (offset < line_len) {
                    fields[count++] = line + offset;
                }
                continue;
            }
        }
        
        offset++;
    }
    
    return count;
}

// Process each line based on mode
void process_line(char *line, CutOptions *options) {
    // Remove trailing newline
    int len = strlen(line);
    if (len > 0 && line[len-1] == '\n') {
        line[len-1] = '\0';
        len--;
    }
    
    if (options->type == 1) {  // Field mode (-f)
        char *fields[MAX_FIELDS];
        int num_fields = split_fields_regex(line, options, fields, MAX_FIELDS);

        int printed = 0;
        for (int i = 0; i < options->field_count; i++) {
            int field_index = options->fields[i] - 1;
            if (field_index >= 0 && field_index < num_fields) {
                if (printed) printf("\t");  // Use tab as output delimiter
                printf("%s", fields[field_index]);
                printed = 1;
            }
        }
        printf("\n");
    } else if (options->type == 2) {  // Character mode (-c)
        for (int i = 0; i < options->field_count; i++) {
            int index = options->fields[i] - 1;
            if (index >= 0 && index < len) {
                putchar(line[index]);
            }
        }
        putchar('\n');
    }
}

int main(int argc, char *argv[]) {
    CutOptions options = {0, {0}, 0, DEFAULT_DELIMITER, NULL, NULL};
    char *list = NULL;
    int opt;

    while ((opt = getopt(argc, argv, "f:c:d:")) != -1) {
        switch (opt) {
            case 'f':
                options.type = 1;
                list = optarg;
                break;
            case 'c':
                options.type = 2;
                list = optarg;
                break;
            case 'd':
                options.delimiter_pattern = optarg;
                break;
            default:
                usage();
        }
    }

    if (!options.type || !list) {
        usage();
    }

    parse_list(list, options.fields, &options.field_count);

    // Compile delimiter pattern (only needed for field mode)
    if (options.type == 1) {
        if (compile_delimiter(&options) != 0) {
            return 1;
        }
    }

    if (optind < argc) {
        for (int i = optind; i < argc; i++) {
            FILE *file = fopen(argv[i], "r");
            if (!file) {
                perror("Error opening file");
                return 1;
            }

            char line[MAX_LINE_LENGTH];
            while (fgets(line, sizeof(line), file)) {
                process_line(line, &options);
            }
            fclose(file);
        }
    } else {
        char line[MAX_LINE_LENGTH];
        while (fgets(line, sizeof(line), stdin)) {
            process_line(line, &options);
        }
    }

    // Cleanup
    if (options.delimiter_regex) {
        pcre_free(options.delimiter_regex);
    }
    if (options.delimiter_extra) {
        pcre_free_study(options.delimiter_extra);
    }

    return 0;
}