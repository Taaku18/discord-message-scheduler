[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]


<!-- PROJECT LOGO -->
<br />
<!-- <div align="center">
  <a href="https://github.com/Taaku18/discord-message-scheduler">
    <img src="logo.png" alt="Logo" width="80" height="80">
  </a> -->

<h3 align="center">Discord Message Scheduler</h3>

  <p align="center">
    A simple Discord Bot that can send scheduled messages.
    <br />
    <a href="https://github.com/Taaku18/discord-message-scheduler#about-the-project"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/Taaku18/discord-message-scheduler/issues">Report Bug</a>
    ·
    <a href="https://github.com/Taaku18/discord-message-scheduler/issues">Request Feature</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#features">Features</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#docker-experimental">Docker (experimental)</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

![Schedule creator screenshot][product-screenshot]

Discord Message Scheduler provides a convenient bot interface to grant users the ability to create scheduled messages via the bot.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Features

* Supports both prefixed and slash commands
* Uses SQLite database
* Modern Discord Modal interface
* Easy to set up
* Docker support

### Built With

* [![Python][Python.org]][Python-url]
* [![discord.py][Discord.py]][Discordpy-url]


<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

Follow these instructions to deploy your own Discord Message Scheduler bot.

### Prerequisites

This bot is build on Python 3.10. You will need to download the latest version of Python using any of the methods below.

* From official website (Any OS): [https://www.python.org/downloads/](https://www.python.org/downloads/).
* Using [Homebrew](https://brew.sh) (MacOS/Linux):
  ```sh
  brew install python@3.10
  ```
* Using APT (Debian/Ubuntu):
  ```sh
  sudo add-apt-repository ppa:deadsnakes/ppa
  sudo apt update
  sudo apt install python3.10 python3.10-dev software-properties-common
  curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10
  ```

You will also need a Discord bot.
1. Create a Discord application at [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Within the settings page, navigate to the **Bot** tab and create a bot
3. (Optional) If you don't want others to invite your bot, then disable **PUBLIC BOT**.
4. Enable **SERVER MEMBERS INTENT** and **MESSAGE CONTENT INTENT** under the Privileged Gateway Intents settings
5. Navigate to **Oauth2** → **URL Generator** tab, click both **bot** and **applications.commands**, and check the following buttons:
   * Read Messages/View Channels
   * Send Messages
   * Send Messages in Thread
   * Send TTS Messages
   * Embed Links
   * Attach Files
   * Read Message History
   * Mention Everyone
   * Use External Emojis
   * Use External Stickers
   * Add Reactions
   * Use Slash Commands
6. Open the link in the **Generated URL** box at the bottom to invite your bot.
   

### Installation

1. Clone or [download](https://github.com/Taaku18/discord-message-scheduler/archive/refs/heads/main.zip) the repo
   ```sh
   git clone https://github.com/Taaku18/discord-message-scheduler.git
   ```
2. Install Python packages
   ```sh
   python3.10 -m pip install -r requirements.txt
   ```
3. Rename `.env.example` to `.env` and replace `BOT-TOKEN` with your bot's token and `BOT-PREFIX` with your desired bot prefix.
   Example `.env` file:
      ```dotenv
       TOKEN=VTDkXNDUzC3KyFoIxNzYx2_d4OQ.PK5K1A.9p0q3Kdi26j0eCa_vu3Ke_39KsL3Kkso83E_gB0
       PREFIX=?
       SYNC_SLASH_COMMANDS=on
      ```
   `SYNC_SLASH_COMMANDS` should be set to "on" the first time you start the bot and every time you update. It should be set to "off" during normal usage since syncing slash commands may take a long time.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

To start the bot, simply run:
```sh
python3.10 start.py
```

<!--_For more examples, please refer to the [Documentation](https://example.com)_-->

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- Docker setup -->
## Docker (experimental)

Alternatively, you can use Docker to deploy this bot.

Ensure you have the latest version of [Docker](https://docs.docker.com/get-docker/) installed (v19.03.0+). You will also need the [Docker Compose Plugin](https://docs.docker.com/compose/install/compose-plugin/).

1. Rename `.env.example` to `.env` and set your environment variables (<a href="#installation">see step 3 above</a>)
2. Build the image
   ```sh
   docker build -t dms:latest .
   ```
3. Start the bot
   ```sh
   docker compose up -d
   ```

To stop the bot do:
```sh
docker compose down
```

To access your bot logs, run `docker ps`. This will show a list of containers.
```sh
CONTAINER ID   IMAGE            COMMAND             CREATED          STATUS                  PORTS     NAMES
58e6aao4c8bd   dms:latest       "python start.py"   14 seconds ago   Up Less than a second             discord-message-scheduler
```
Find the **CONTAINER ID** of the container named "discord-message-scheduler" and run `docker logs <CONTAINER ID>`.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->
## Roadmap

- [x] Basic help and schedule command interfaces
- [ ] Implement list/delete command
    - [ ] Allow server staff access to these commands
- [ ] Implement reporting interface to remove abusive scheduled messages
- [ ] Permissions system
- [ ] Add GitHub workflow for testing, linting, building Docker image
- [ ] Create a Docker image

See the [open issues](https://github.com/github_username/repo_name/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. If you made any code changes, use `black .` to format the code
4. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
5. Push to the Branch (`git push origin feature/AmazingFeature`)
6. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LICENSE -->
## License

Distributed under GNU General Public License v3.0. See `LICENSE.txt` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Contact me via Discord:

Taku - [taku#3343](https://discord.com/)

Project Link: [https://github.com/Taaku18/discord-message-scheduler](https://github.com/Taaku18/discord-message-scheduler)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* Inspired by [bjsbrar/DiscordMessageScheduler](https://github.com/bjsbrar/DiscordMessageScheduler)


<p align="right">(<a href="#readme-top">back to top</a>)</p>


[contributors-shield]: https://img.shields.io/github/contributors/Taaku18/discord-message-scheduler.svg?style=for-the-badge
[contributors-url]: https://github.com/Taaku18/discord-message-scheduler/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/Taaku18/discord-message-scheduler.svg?style=for-the-badge
[forks-url]: https://github.com/Taaku18/discord-message-scheduler/network/members
[stars-shield]: https://img.shields.io/github/stars/Taaku18/discord-message-scheduler.svg?style=for-the-badge
[stars-url]: https://github.com/Taaku18/discord-message-scheduler/stargazers
[issues-shield]: https://img.shields.io/github/issues/Taaku18/discord-message-scheduler.svg?style=for-the-badge
[issues-url]: https://github.com/Taaku18/discord-message-scheduler/issues
[license-shield]: https://img.shields.io/github/license/Taaku18/discord-message-scheduler.svg?style=for-the-badge
[license-url]: https://github.com/Taaku18/discord-message-scheduler/blob/master/LICENSE.txt
[product-screenshot]: sample_image.png
[Python.org]: https://img.shields.io/badge/Python-35495E?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://python.org 
[Discord.py]: https://img.shields.io/badge/discord.py-0769AD?style=for-the-badge&logo=data:image/png;base64,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
[Discordpy-url]: https://github.com/Rapptz/discord.py
