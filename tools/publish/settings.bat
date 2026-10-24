@echo off
rem This folder is expected to sit directly inside the collector folder.
rem Change SOURCE_DIR if the source databases are stored elsewhere.
set "SOURCE_DIR=..\..\database\main"

set "CURRENT_DB=%SOURCE_DIR%\live_data.db"
set "AUDIENCE_DB=%SOURCE_DIR%\streamer_audience.db"
