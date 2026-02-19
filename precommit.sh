#!/bin/bash

# Function to install the pre-commit hook
install_hook() {
    HOOK_DIR=".git/hooks"
    HOOK_PATH="$HOOK_DIR/pre-commit"

    # Create hooks directory if it doesn't exist
    mkdir -p "$HOOK_DIR"

    # Create the pre-commit hook
    cat > "$HOOK_PATH" << EOL
#!/bin/bash
$(dirname "\$0")/precommit.sh
EOL

    # Make the hook executable
    chmod +x "$HOOK_PATH"

    echo "Pre-commit hook installed successfully."
}

# Function to uninstall the pre-commit hook
uninstall_hook() {
    HOOK_PATH=".git/hooks/pre-commit"
    rm -f "$HOOK_PATH"
    echo "Pre-commit hook uninstalled successfully."
}

# Check if the script is called with 'install' parameter
if [ "$1" = "install" ]; then
    install_hook
    exit 0
fi

# Check if the script is called with 'uninstall' parameter
if [ "$1" = "uninstall" ]; then
    uninstall_hook
    exit 0
fi

get_plugin_core_name() {
    echo "$(basename "$1" | sed 's/pre_plugin_\(.*\)\.sh/\1/')"
}

# Function to run a plugin and capture its output and status
run_plugin() {
    plugin="$1"
    # Ensure tmp_dir exists (should be created before calling this)
    if [ -z "$tmp_dir" ] || [ ! -d "$tmp_dir" ]; then
        printf "Error: tmp_dir is not set or does not exist.\n" >&2
        return 1 # Or exit, depending on desired behavior
    fi

    plugin_core_name=$(get_plugin_core_name "$plugin")
    printf " Starting plugin: %s" "$plugin_core_name" >&2

    # Check if plugin exists and is executable
    if [ ! -f "$plugin" ]; then
        printf "\nError: Plugin file %s does not exist\n" "$plugin" >&2
        return 1 # Indicate failure, but don't exit the main script
    fi

    if [ ! -x "$plugin" ]; then
        printf "\nError: Plugin file %s is not executable\n" "$plugin" >&2
        return 1 # Indicate failure
    fi

    printf "\n" >&2

    # Create temporary files INSIDE the main tmp_dir for easier cleanup
    # Metadata file (stores status, name, output file path)
    local result_meta_file
    result_meta_file=$(mktemp "$tmp_dir/result.XXXXXX")
    # Output file (stores raw stdout/stderr)
    local result_output_file="$result_meta_file.out"

    # Run the plugin and capture output
    # Use /bin/sh explicitly if needed, or just run directly if PATH is reliable
    "$plugin" > "$result_output_file" 2>&1
    local status=$? # Capture status immediately

    # Store metadata
    printf "name='%s'\n" "$plugin" > "$result_meta_file"
    # Store the PATH to the output file, not the content
    printf "output_file='%s'\n" "$result_output_file" >> "$result_meta_file"
    printf "status='%s'\n" "$status" >> "$result_meta_file"

    # Append the path to the metadata file to the central results list
    # This replaces the previous behavior of printing it to stdout
    printf "%s\n" "$result_meta_file" >> "$tmp_dir/results.txt"

    # Don't return status here, it's stored in the file
    # The caller should check the status read from the file later
}

# Function to render the output of a plugin
render_plugin_output() {
    result_meta_file="$1"
    # Default values in case sourcing fails or file is incomplete
    name=""
    output_file=""
    status=""

    # Check if meta file exists before sourcing
    if [ -f "$result_meta_file" ]; then
        # Source the temporary file to get the values
        # This is now safe as it only contains simple assignments
        . "$result_meta_file"
    else
        printf "\n\nError: Result metadata file not found: %s\n" "$result_meta_file" >&2
        return
    fi

    local plugin_core_name
    plugin_core_name=$(get_plugin_core_name "$name")
    printf "\n\nPlugin finished with exit code %s: %s" "$status" "$plugin_core_name"
    printf "\n=================================\n"

    # Check if output file exists before catting
    if [ -f "$output_file" ]; then
        # Use cat to print the output, indented
        # Using printf ensures consistent handling of special chars like %
        # Using sed ensures indentation
        printf "%s" "$(cat "$output_file")" | sed 's/^/  /'
        printf "\n" # Ensure a newline after the output
    else
        printf "  Error: Output file not found: %s\n" "$output_file" >&2
    fi
}

# Function to generate the summary table in Markdown format
generate_summary_table() {
    echo ""
    echo "## Plugin Summary"
    echo ""
    
    # Print table header with borders
    printf "+----------------------+----------+\n"
    printf "| %-20s | %-8s |\n" "Plugin" "Status"
    printf "+----------------------+----------+\n"
    
    # Read results meta file paths
    while IFS= read -r result_meta_file; do
        [ ! -f "$result_meta_file" ] && continue

        # Initialize variables for safety
        name=""
        status=""
        output_file=""

        # Source the meta file (safe now)
        . "$result_meta_file"

        # Determine status text
        local status_text="Success"
        # Check status first (more reliable than parsing output)
        # Ensure status is treated as a number
        if ! [[ "$status" =~ ^[0-9]+$ ]]; then
             status_text="Unknown" # Status wasn't a number
        elif [ "$status" -ne 0 ]; then
             status_text="Failed"
        # Only check output file content if status was 0 and file exists
        elif [ -f "$output_file" ] && grep -q "No files to lint" "$output_file"; then
             status_text="No files"
        elif [ ! -f "$output_file" ]; then
             status_text="No output" # Output file missing, even if status is 0
        fi

        local name_core_plugin
        name_core_plugin=$(get_plugin_core_name "$name")
        printf "| %-20s | %-8s |\n" "$name_core_plugin" "$status_text"
    done < "$tmp_dir/results.txt"

    # Print table footer
    printf "+----------------------+----------+\n"
}

# Run checks
echo "Running checks..."

# Initialize array for plugin results
declare -a plugin_results

# Create a temporary directory for results
tmp_dir=$(mktemp -d)
touch "$tmp_dir/results.txt" # Ensure results file exists
# Export tmp_dir so background processes can access it
export tmp_dir
trap 'rm -rf "$tmp_dir"' EXIT

# Store list of plugins in a temporary file
chmod +x *.sh
find . -maxdepth 1 -type f -name "pre_plugin_*.sh" -print0 > "$tmp_dir/plugins.txt"

echo

# Process each plugin in parallel
counter=0

# Convert null-separated values to newline-separated in a temporary file
tr '\0' '\n' < "$tmp_dir/plugins.txt" > "$tmp_dir/plugins_nl.txt"

# Read from the newline-separated file
while read -r plugin; do
    counter=$((counter+1))
    # Run plugin in the background
    run_plugin "$plugin" &
done < "$tmp_dir/plugins_nl.txt"

# Wait for all background plugin processes to complete
wait

# Read results into array (now reading from the file populated by the plugins)
while IFS= read -r result_file; do
    plugin_results+=("$result_file")
done < "$tmp_dir/results.txt"

# Wait for all plugins to finish and render output
for result_file in "${plugin_results[@]}"; do
    render_plugin_output "$result_file"
done

# Generate summary table
generate_summary_table

# Check if any plugin failed
check_plugin_failures() {
    local failed=0
    local status

    for result_meta_file in "${plugin_results[@]}"; do
        # Reset status for each loop iteration
        status=""
        if [ -f "$result_meta_file" ]; then
             . "$result_meta_file"
             # Check if status is non-zero (and numeric)
             if [[ "$status" =~ ^[0-9]+$ ]] && [ "$status" -ne 0 ]; then
                 failed=1
             fi
        else
             : # Do nothing, or log error
        fi
    done
    return $failed
}

echo
if ! check_plugin_failures; then
    echo "Pre-commit checks failed."
    exit 1
fi

# Trap handles cleanup of tmp_dir and its contents

echo "Pre-commit checks passed successfully."
exit 0
