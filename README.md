# InstalingPy

mini_bomba's 3rd (or 4th?) iteration of an API library and automation framework for instaling.pl

Kept secret for 5 years and now available under the most copyleft license I could find (AGPLv3, see the [LICENSE](https://github.com/mini-bomba/InstalingPy/blob/master/LICENSE) file)

## Features
- API bindings to the most useful instaling.pl endpoints
- 3 modes of operation:
  - interactive - Acts as a simple CLI client for instaling.pl, while recording encountered prompts in the database and showing hints when available
  - automatic - Asks for username and password on stdin, then solves a whole session automatically
  - scheduled (the main mode) - Runs as a daemon (in the background) while scheduling the automatic solver to run at randomply picked times as configured
- scheduled mode supports multiple users with separate configuration options
- automatically learns words by recording the answers shown after submitting a mistake
- can insert random mistakes, including:
  - submitting nothing
  - submitting words with incorrect casing (lowercase)
  - submitting synonyms (automatically derived from known words, works best with simple word definitions)
  - the chance of submitting a mistake is higher for recently learnt words
    - based on the amount of times the word was seen
    - configurable!
- configurable random delays to simulate the user performing various actions, including
  - starting a new session
  - thinking
  - typing (per character)
  - really trying to remember what the correct word is (aka. extended thinking before making a mistake)
  - proceeding to the next question
  - skipping an ad
  - literally getting distracted by some random discord @everyone ping for 5 minutes
- discord notifications about profiles being run
- scheduled mode has a custom json-based "rcon" (remote control) protocol for manually triggering, rescheduling or cancelling profiles and for hot-reloading the configuration file
- detailed statistics accessible via Grafana (dashboard included: [`grafana_dashboard.json`](https://github.com/mini-bomba/InstalingPy/blob/master/grafana_dashboard.json))
  - see the number of tasks solved by all configured profiles, words and translations learnt
  - browse the dumbest (longest) translations or prompts ever seen
  - see what words a given profile has seen the most and when it most commonly runs

### Grafana dashboard screenshots
![quick summary](https://github.com/mini-bomba/InstalingPy/raw/master/screenshots/grafana1.png)
![longest entries](https://github.com/mini-bomba/InstalingPy/raw/master/screenshots/grafana2.png)
![more longest entries](https://github.com/mini-bomba/InstalingPy/raw/master/screenshots/grafana3.png)
![most translations](https://github.com/mini-bomba/InstalingPy/raw/master/screenshots/grafana4.png)
![personal stats](https://github.com/mini-bomba/InstalingPy/raw/master/screenshots/grafana5.png)

## Installing/running

Note: I am opensourcing this project as it is no longer useful to me - I've graduated from the school that required us to use this website daily.
Do not expect quick support or frequent maintenance, but feel free to fork the project and use it, as long as you respect [the license](https://github.com/mini-bomba/InstalingPy/blob/master/LICENSE) and make your modified version public.

### Requirements
- Linux. Any modern distribution will do, any processor architecture, as long as it can handle python and MariaDB.
  - Technically this is python, so it can run on Windows, but the project wasn't made with Windows in mind and might require changes to run correctly. The idea of this project was to have a service that can run unattended on a random cloud server, and Windows Server is a waste of time and money for such a small project.
- Python 3, 3.10 is likely the minimum
- a MySQL or MariaDB database service
- (optional) Docker or Podman if you'd like to run this in a container. a Dockerfile is included.
  - I personally use Podman containers running under a low-privilege user.
- (optional) Grafana for the nice dashboard
  - Prometheus is NOT needed

### actually installing this thing
- Create a database. I called mine `InstalingBot`.
- Initialize the database using the `sql/init.sql` script.
  - IMPORTANT! Review and edit the script before running it! If the database name is different than `InstalingBot`, or if you don't want to use unix socket authentication, you will need to modify the script.
- If you want to use containers, build the container using the provided `Dockerfile` (`docker build -t instaling .`)
- If you don't want to use containers, install the pip requirements from the `requirements.txt` file. Using a virtual environment is recommended.
- Make a `shared` directory (must be in the repo root if you don't use containers, otherwise it can be wherever you want)
- Make a copy of the `config.example.json` file, put it in the `shared` directory, rename it to `config.json`. Modify the settings to fit your setup and remove all comments.
  - if you use containers, all paths in the config will be paths in the container
  - the working directory and location of the scripts inside the container is /instaling
- I think that's all. You should be able to run the scripts now.
  - For container users: remember to mount the MariaDB unix socket, `/etc/localtime`, a logs directory to `/instaling/logs`, and the `shared` directory to `/instaling/shared`
    - the default container init command is `python scheduled.py` (= the container runs the scheduler by default)
    - For reference, this is the command I use to start the container:
```bash
podman run --rm --ith instaling --name instaling -v /var/run/mysqld/mysqld.sock:/mysqld.sock -v /etc/localtime:/etc/localtime:ro -v /var/lib/instaling/logs:/instaling/logs -v /var/lib/instaling/shared:/instaling/shared instaling
```
- If you'd like to use grafana, set up the MariaDB database as a data source, then import the dashboard ([`grafana_dashboard.json`](https://github.com/mini-bomba/InstalingPy/raw/master/grafana_dashboard.json))

## License and credits
This iteration of InstalingPy is the result of work done during the last 2 years (2022-2024), but it builds on the experience gained from previous iterations and other private projects done over the course of the last 5 years. (2019-2024)

InstalingPy is available under AGPLv3, but it wouldn't be possible without the following projects:

- The two direct python dependencies:
  - [`aiomysql`](https://github.com/aio-libs/aiomysql), the asynchronous bindings for the MySQL database.
  - [`httpx`](https://github.com/encode/httpx/), the awesome (a)sync HTTP library with an API closely resembling the `requests` library.
- [Python](https://www.python.org/), the programming language used in this project
- [MariaDB](https://github.com/MariaDB/server), the SQL server, a fork of MySQL
- [Podman](https://github.com/containers/podman), the Docker alternative that makes me go crazy about user namespaces, uid mappings and bridging the netowork namespaces with pasta
- [Grafana](https://github.com/grafana/grafana), that software for making cool visualizations of what my software is doing
- [Linux](https://kernel.org/)
