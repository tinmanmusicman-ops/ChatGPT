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
