"""File operation utilities for Qualytics CLI."""
import os


def distinct_file_content(file_path):
    """Remove duplicate lines from a file."""
    # Check if the file exists before opening it
    if not os.path.exists(file_path):
        return  # Return early if the file doesn't exist

    with open(file_path) as file:
        # Using a set to automatically get distinct lines
        distinct_lines = set(file.readlines())

    with open(file_path, "w") as file:
        for line in distinct_lines:
            file.write(line)


def log_error(message, file_path):
    """Log an error message to a file."""
    # Check if the file exists before opening it
    if not os.path.exists(file_path):
        with open(file_path, "w"):
            pass  # Create an empty file if it doesn't exist

    with open(file_path, "a") as file:
        file.write(message + "\n")
        file.flush()
