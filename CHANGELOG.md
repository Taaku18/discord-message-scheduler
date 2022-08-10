# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]


## [1.2.2] - 2022-08-09
### Added
- Per channel and guild limit
  - Currently set to 50 per channel, 250 per guild
- Relative time to `/schedule show` and `/schedule list`


## [1.2.1] - 2022-08-09
### Fixed
- Page limit should be 10 for `/schedule list`

### Changed
- Rewrote Dockerfile to use PDM


## [1.2] - 2022-08-09
### Added
- Pyright static checker
- Added `/schedule list` and `/schedule remove`
- Added version info to `/info` and `/help` commands

### Fixed
- Many internal typing issues
- Prevent other users from clicking your buttons

### Changed
- Optimized Docker image
- `/schedule` command is now `/schedule create`


## [1.1.1] - 2022-08-07
### Added
- Use pdm as our package manager
- Use dateparser as the default time parser
  - dateutil is now optional and a drop-in replacement to dateparser

### Fixed
- Ping support wasn't working for older SQLite versions


## [1.1] - 2022-08-06
### Added
- Support for @ping within messages
- Internal framework to migrate SQLite database
- Docker image support and README guide for Docker
- Add uvloop for speedup
- Allow default timezones to be changed

### Changed
- Renamed and moved default database file from `/schedule.sqlite` to `/data/schedule.db`


## [1.0] - 2022-08-05
### Added
- Initial code base for the bot


[Unreleased]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.2.2...HEAD
[1.2.2]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.2...v1.2.1
[1.2]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.1.1...v1.2
[1.1.1]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.1...v1.1.1
[1.1]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.0...v1.1
[1.0]: https://github.com/Taaku18/discord-message-scheduler/releases/tag/v1.0
