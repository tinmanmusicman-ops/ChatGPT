# Migration Log

## Config Editor
- Copied configuration GUI scripts (config_editor.py, ConfigGUI.py, uild_config_*) into config-editor/scripts/.
- Copied config data (config.json, history/prefs) and Docs into config-editor/source/, and PDFs into config-editor/bot-assets/.

## Release Tracker
- Copied Indeed.py, IsitScam.py, batch runners into 
elease-tracker/scripts/ and archived logs into 
elease-tracker/bot-assets/.
- Placed a small overview note in 
elease-tracker/source/OVERVIEW.md to describe the logs.

## Automation Assistant
- Copied automation scripts (send_irsfax.py, seam_thermostat_temp.py, midi_player_gui.py, prefs_demo.py) into utomation-assistant/scripts/.
- Archived supporting configs (SA_key.json, Test.json, seam_config.example.json) into utomation-assistant/bot-assets/ and added an overview doc.

## Path Updates
- No .py files contained hardcoded paths to the new folders, so no updates were required.

## Notes
- Left the original files intact under C:\ChatGPT\Indeed while copying duplicates into the modular workspace.
- Not sure how to map the large Ref/ directory into the new projects; further direction would help.
# Thermostats Project
- Copied seam_thermostat_temp.py into Thermostats/scripts/ and related configs into Thermostats/bot-assets/.

## Shared Resources
- Added shared/Glocal.json and updated Thermostats/scripts/seam_thermostat_temp.py to load it via SA_KEY_PATH.

## Thermostats config cleanup
- Reduced Thermostats/bot-assets/config.json to keys actually referenced by seam_thermostat_temp.py so the config editor shows only project-specific settings.

## Config editor launch helpers
- Added launch_config_editor.py helpers in each bot-assets folder so the shared editor opens from the calling directory.

## Config editor links
- Added config_editor.py hard links in each ot-assets/ folder (config-editor, release-tracker, automation-assistant, Thermostats) so the shared script can be launched directly from these directories.

## Shared resources update
- Added shared Gmail/spreadsheet defaults to shared/Glocal.json and taught Thermostats script to pull missing values from that file.

## Unified launcher
- Added launch_config_editor.py at the ai-bots root to scan each project's ot-assets/config.json and let you pick which one the shared editor opens.

## Project selector
- Config editor now enumerates all i-bots/*/bot-assets/config.json files at launch and asks which one to open so the GUI automatically knows the correct folder.

## Scams project
- Created i-bots/Scams/{source,bot-assets,scripts} and moved IsitScam.py plus a trimmed scripts/config.json there. The script now loads shared defaults from shared/Glocal.json.

## Fax migration
- Added i-bots/Fax/{source,bot-assets,scripts}, moved send_irsfax.py into scripts, and created ot-assets/config.json plus adjusted 
esolve_config_path.


## Jobs migration
- Added i-bots/Jobs/{source,bot-assets,scripts}, created a trimmed ot-assets/config.json, and updated Indeed.py to load that config plus shared defaults.
