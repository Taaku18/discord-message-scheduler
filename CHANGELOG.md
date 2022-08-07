# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Changed
- Optimized Docker image


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


[Unreleased]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.1...v1.1.1
[1.1]: https://github.com/Taaku18/discord-message-scheduler/compare/v1.0...v1.1
[1.0]: https://github.com/Taaku18/discord-message-scheduler/releases/tag/v1.0