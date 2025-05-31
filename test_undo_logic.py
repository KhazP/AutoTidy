import sys
import os
import shutil
from pathlib import Path
import json

# Add the parent directory to sys.path to allow imports of project modules
# Assuming this script is run from a directory that has undo_manager.py etc. as siblings or in PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

try:
    from undo_manager import UndoManager
except ImportError:
    print("Failed to import UndoManager. Make sure it's in the Python path.")
    print("If running with 'run_in_bash_session', ensure undo_manager.py is in the root of the repo.")
    sys.exit(1)


# --- Test Setup ---
TEST_DIR_STR = "/tmp/autotidy_test_undo" # Must match the bash setup
TEST_DIR = Path(TEST_DIR_STR)

class MockConfigManager:
    def get_config_dir_path(self):
        return TEST_DIR # This is where autotidy_history.jsonl is located

def print_test_header(title):
    print(f"\n--- {title} ---")

def assert_condition(condition, success_msg, failure_msg):
    if condition:
        print(f"PASS: {success_msg}")
        return True
    else:
        print(f"FAIL: {failure_msg}")
        return False

# File paths (must match bash setup)
# Run 1
RUN1_ORIG_FILE1_STR = f"{TEST_DIR_STR}/source_folder/run1_file1.txt"
RUN1_DEST_FILE1_STR = f"{TEST_DIR_STR}/archive_folder/2023-10-26/run1_file1.txt"
RUN1_ORIG_FILE2_STR = f"{TEST_DIR_STR}/source_folder/run1_file2.txt"
RUN1_DEST_FILE2_STR = f"{TEST_DIR_STR}/archive_folder/2023-10-26/run1_file2.txt"
# Run 2
RUN2_ORIG_FILE1_STR = f"{TEST_DIR_STR}/source_folder/run2_file1.txt"
RUN2_DEST_FILE1_STR = f"{TEST_DIR_STR}/archive_folder/2023-10-27/run2_file1.txt"
# Run 3
RUN3_ORIG_FILE1_STR = f"{TEST_DIR_STR}/source_folder/run3_file1.txt"
RUN3_DEST_FILE1_STR = f"{TEST_DIR_STR}/archive_folder/2023-10-28/run3_file1.txt"
RUN3_ORIG_FILE2_STR = f"{TEST_DIR_STR}/source_folder/run3_file2.txt" # Dest for this will be missing
RUN3_DEST_FILE2_STR = f"{TEST_DIR_STR}/archive_folder/2023-10-28/run3_file2.txt"


def main():
    config_manager = MockConfigManager()
    undo_manager = UndoManager(config_manager)

    # --- Test get_history_runs() ---
    print_test_header("Testing get_history_runs()")
    runs = undo_manager.get_history_runs()
    assert_condition(len(runs) == 3, f"Found {len(runs)} runs as expected.", f"Expected 3 runs, found {len(runs)}")
    if runs:
        # Check if sorted by start_time descending (most recent first)
        run_ids_in_order = [r['run_id'] for r in runs]
        expected_order = ["test-run-3", "test-run-2", "test-run-1"]
        assert_condition(run_ids_in_order == expected_order,
                         f"Runs correctly sorted: {run_ids_in_order}",
                         f"Runs incorrectly sorted. Expected {expected_order}, got {run_ids_in_order}")
        for run in runs:
            print(f"  Run ID: {run['run_id']}, Start: {run['start_time']}, Count: {run['action_count']}")


    # --- Test get_run_actions() ---
    print_test_header("Testing get_run_actions('test-run-1')")
    run1_actions = undo_manager.get_run_actions("test-run-1")
    assert_condition(len(run1_actions) == 2, "Found 2 actions for test-run-1.", f"Expected 2 actions for test-run-1, found {len(run1_actions)}")
    if run1_actions:
        # Check if sorted by timestamp ascending
        action_timestamps = [a['timestamp'] for a in run1_actions]
        is_sorted_asc = all(action_timestamps[i] <= action_timestamps[i+1] for i in range(len(action_timestamps)-1))
        assert_condition(is_sorted_asc, "Actions in run-1 correctly sorted by timestamp.", "Actions in run-1 NOT sorted by timestamp.")
        for action in run1_actions:
            print(f"  Action: {action['original_path']} -> {action['destination_path']} at {action['timestamp']}")

    # --- Test undo_action() ---
    print_test_header("Testing undo_action()")

    # Scenario 1: Successful undo
    print("\n  Scenario 1: Successful undo (run1_file1)")
    action_to_undo_s1 = { # From history: first action of test-run-1
        "run_id": "test-run-1", "original_path": RUN1_ORIG_FILE1_STR,
        "action_taken": "MOVED", "destination_path": RUN1_DEST_FILE1_STR,
        "timestamp": "2023-10-26T10:00:00Z"
    }
    dest_s1 = Path(RUN1_DEST_FILE1_STR)
    orig_s1 = Path(RUN1_ORIG_FILE1_STR)

    assert_condition(dest_s1.exists(), f"Pre-check: Destination '{dest_s1}' exists.", f"Pre-check FAIL: Destination '{dest_s1}' does not exist.")
    assert_condition(not orig_s1.exists(), f"Pre-check: Original '{orig_s1}' does not exist.", f"Pre-check FAIL: Original '{orig_s1}' already exists.")

    success, message = undo_manager.undo_action(action_to_undo_s1)
    assert_condition(success, f"undo_action successful: {message}", f"undo_action failed: {message}")
    assert_condition(not dest_s1.exists(), f"File '{dest_s1}' correctly removed from destination.", f"File '{dest_s1}' still exists at destination.")
    assert_condition(orig_s1.exists(), f"File '{orig_s1}' correctly moved to original location.", f"File '{orig_s1}' not found at original location.")

    # Scenario 2: Destination file for undo is missing
    print("\n  Scenario 2: Undo where destination file is missing")
    action_to_undo_s2 = { # A file that was "moved" but its destination is already gone
        "run_id": "test-run-x", "original_path": f"{TEST_DIR_STR}/source_folder/file_ghost_orig.txt",
        "action_taken": "MOVED", "destination_path": f"{TEST_DIR_STR}/archive_folder/ghost_dest.txt", # This file won't exist
        "timestamp": "2023-10-26T10:00:00Z"
    }
    dest_s2 = Path(action_to_undo_s2["destination_path"])
    assert_condition(not dest_s2.exists(), f"Pre-check: Test file '{dest_s2}' correctly does not exist.", f"Pre-check FAIL: Test file '{dest_s2}' exists.")

    success, message = undo_manager.undo_action(action_to_undo_s2)
    assert_condition(not success and "does not exist" in message.lower(),
                     f"undo_action correctly failed for missing destination: {message}",
                     f"undo_action did not fail as expected or wrong message for missing dest: {message}")

    # Scenario 3: Original path for undo already exists
    print("\n  Scenario 3: Undo where original path (target of undo) already exists")
    # We'll use run1_file1 which was successfully undone in Scenario 1, so its original_path now exists.
    # We need to re-create its "destination" file to attempt the undo again.
    dest_s3 = Path(RUN1_DEST_FILE1_STR) # This was the dest_s1, it's empty now
    orig_s3 = Path(RUN1_ORIG_FILE1_STR) # This was orig_s1, it now contains the file

    Path(dest_s3.parent).mkdir(parents=True, exist_ok=True) # Ensure parent dir
    with open(dest_s3, "w") as f: f.write("dummy content for S3") # Re-create the "moved" file

    assert_condition(dest_s3.exists(), f"Pre-check: Destination for S3 '{dest_s3}' re-created.", f"Pre-check FAIL: Dest S3 '{dest_s3}' not created.")
    assert_condition(orig_s3.exists(), f"Pre-check: Original for S3 '{orig_s3}' already exists.", f"Pre-check FAIL: Original S3 '{orig_s3}' does not exist.")

    success, message = undo_manager.undo_action(action_to_undo_s1) # Using same action as S1
    assert_condition(not success and "already exists" in message.lower(),
                     f"undo_action correctly failed as original path exists: {message}",
                     f"undo_action did not fail as expected or wrong message for existing original: {message}")
    # Cleanup S3: remove the manually created dest_s3, leave orig_s3 as it was (undone state)
    if dest_s3.exists(): os.remove(dest_s3)


    # --- Test undo_batch() ---
    print_test_header("Testing undo_batch()")

    # Scenario 1: Successful full batch undo (test-run-2)
    print("\n  Scenario B1: Successful full batch undo (test-run-2)")
    run2_dest_file1 = Path(RUN2_DEST_FILE1_STR)
    run2_orig_file1 = Path(RUN2_ORIG_FILE1_STR)

    assert_condition(run2_dest_file1.exists(), f"Pre-check B1: Dest '{run2_dest_file1}' exists.", f"Pre-check B1 FAIL: Dest '{run2_dest_file1}' missing.")
    assert_condition(not run2_orig_file1.exists(), f"Pre-check B1: Orig '{run2_orig_file1}' does not exist.", f"Pre-check B1 FAIL: Orig '{run2_orig_file1}' exists.")

    results_b1 = undo_manager.undo_batch("test-run-2")
    print(f"  Batch undo results B1: {results_b1.get('summary')}")
    for msg in results_b1.get('messages', []): print(f"    {msg}")

    assert_condition(results_b1['success_count'] == 1 and results_b1['failure_count'] == 0,
                     "Batch undo summary correct for B1.", "Batch undo summary incorrect for B1.")
    assert_condition(not run2_dest_file1.exists(), f"File '{run2_dest_file1}' correctly removed post-batch.", f"File '{run2_dest_file1}' still exists post-batch.")
    assert_condition(run2_orig_file1.exists(), f"File '{run2_orig_file1}' correctly restored post-batch.", f"File '{run2_orig_file1}' not found post-batch.")

    # Scenario 2: Partial success batch undo (test-run-3)
    # RUN3_DEST_FILE1 exists, RUN3_DEST_FILE2 does NOT exist (as per bash setup)
    print("\n  Scenario B2: Partial success batch undo (test-run-3)")
    run3_dest_file1 = Path(RUN3_DEST_FILE1_STR)
    run3_orig_file1 = Path(RUN3_ORIG_FILE1_STR)
    run3_dest_file2 = Path(RUN3_DEST_FILE2_STR) # This one is missing
    run3_orig_file2 = Path(RUN3_ORIG_FILE2_STR)


    assert_condition(run3_dest_file1.exists(), f"Pre-check B2: Dest '{run3_dest_file1}' exists.", f"Pre-check B2 FAIL: Dest '{run3_dest_file1}' missing.")
    assert_condition(not run3_dest_file2.exists(), f"Pre-check B2: Dest '{run3_dest_file2}' correctly does not exist.", f"Pre-check B2 FAIL: Dest '{run3_dest_file2}' exists.")
    assert_condition(not run3_orig_file1.exists(), f"Pre-check B2: Orig '{run3_orig_file1}' does not exist.", f"Pre-check B2 FAIL: Orig '{run3_orig_file1}' exists.")
    assert_condition(not run3_orig_file2.exists(), f"Pre-check B2: Orig '{run3_orig_file2}' does not exist.", f"Pre-check B2 FAIL: Orig '{run3_orig_file2}' exists.")

    results_b2 = undo_manager.undo_batch("test-run-3")
    print(f"  Batch undo results B2: {results_b2.get('summary')}")
    for msg in results_b2.get('messages', []): print(f"    {msg}")

    assert_condition(results_b2['success_count'] == 1 and results_b2['failure_count'] == 1,
                     "Batch undo summary correct for B2 (1 success, 1 failure).",
                     f"Batch undo summary incorrect for B2. Got S:{results_b2['success_count']} F:{results_b2['failure_count']}")
    # Check file states for B2
    assert_condition(not run3_dest_file1.exists(), f"File '{run3_dest_file1}' (success case) correctly removed post-batch B2.", f"File '{run3_dest_file1}' (success case) still exists post-batch B2.")
    assert_condition(run3_orig_file1.exists(), f"File '{run3_orig_file1}' (success case) correctly restored post-batch B2.", f"File '{run3_orig_file1}' (success case) not found post-batch B2.")
    assert_condition(not run3_dest_file2.exists(), f"File '{run3_dest_file2}' (failure case) still does not exist post-batch B2.", f"File '{run3_dest_file2}' (failure case) now exists post-batch B2 (unexpected).")
    assert_condition(not run3_orig_file2.exists(), f"File '{run3_orig_file2}' (failure case) still not restored post-batch B2 (expected).", f"File '{run3_orig_file2}' (failure case) was restored post-batch B2 (unexpected).")

    print("\n--- All tests complete ---")

if __name__ == "__main__":
    # Ensure the current working directory for the script is the repo root or TEST_DIR for file operations
    # The script itself is created in the repo root by the agent.
    # Paths used in the script are absolute so CWD shouldn't be an issue for file ops.
    main()
