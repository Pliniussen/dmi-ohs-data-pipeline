Dette projekt er et setup til data engineering projekter, hvor der bruges Python, pytest og PostgreSQL.

Projektet er sat op med Docker, Docker Compose og Dev Container.

Der er også sat en pgAdmin container op, hvor forbindelsen til postgres databasen er præ-konfigureret.

# Setup Guide
## Installer WSL og Docker Desktop

### Windows Subsystem for Linux (WSL)

Docker skal bruge WSL for at kunne køre. For at installere det:
1. Åben PowerShell som Administrator.
2. Brug kommandoen ``wsl --install``
3. Genstart din computer
4. Åben igen PowerShell
5. Verificer installationen med kommandoen ``wsl --version``

### Docker Desktop

1. Download Docker Desktop til windows fra https://www.docker.com/products/docker-desktop/
2. Installer Docker Desktop
3. Åben docker desktop
4. Åben PowerShell og brug kommandoen ``docker --version`` for at verificere at installationen er korrekt
5. Brug kommandoen ``docker run hello-world``. Du har nu startet din første Docker container.

---
---

# Container system overview
```mermaid
	flowchart TB
    dh["Docker Hub"] L_dh_img1_0@-- download --> img1["Image: postgres:16"] & img3["Image: dpage/pgadmin4"]
    img1 L_img1_con1_0@-- start --> con1["Service: db"]
    fil1["Dockerfile"] L_fil1_img2_0@-- build --> img2["Application image"]
    img2 L_img2_con2_0@-- start --> con2["Service: app"] & con3["Service: tests"]
    con2 L_con2_con1_0@-. depends on .-> con1
    con3 L_con3_con1_0@-. depends on .-> con1
    img3 L_img3_con4_0@-- start --> con4["Service: pgadmin"]
    con4 L_con4_con1_0@-. depends on .-> con1
    con1 -- save data in --> n1["Volume: postgres_data"]
    con4 -- saves data in --> n2["Volume: pgadmin_data"]

    dh@{ shape: cloud}
    img1@{ shape: subproc}
    img3@{ shape: subproc}
    con1@{ shape: rounded}
    fil1@{ shape: card}
    img2@{ shape: subproc}
    con2@{ shape: rounded}
    con3@{ shape: rounded}
    con4@{ shape: rounded}
    n1@{ shape: cyl}
    n2@{ shape: cyl}
    style dh fill:#BBDEFB,stroke:#2962FF,color:#000000
    style img1 fill:#FFCDD2,stroke:#D50000,color:#000000
    style img3 fill:#FFCDD2,stroke:#D50000,color:#000000
    style con1 fill:#C8E6C9,stroke:#00C853,color:#000000
    style fil1 fill:#FFF9C4,stroke:#FFD600,color:#000000
    style img2 fill:#FFCDD2,stroke:#D50000,color:#000000
    style con2 fill:#C8E6C9,stroke:#00C853,color:#000000
    style con3 fill:#C8E6C9,stroke:#00C853,color:#000000
    style con4 fill:#C8E6C9,stroke:#00C853,color:#000000
    style n1 fill:#E1BEE7,color:#000000,stroke:#AA00FF
    style n2 fill:#E1BEE7,stroke:#AA00FF,color:#000000
    linkStyle 6 stroke:#cccccc,fill:none
    linkStyle 7 stroke:#cccccc,fill:none
    linkStyle 9 stroke:#cccccc,fill:none

```
Systemet består af 4 services:
- ``app`` servicen kører applikationskoden
- ``tests`` servicen kører testene
- ``db`` servicen kører PostgreSQL
- ``pgadmin`` servicen kører pgAdmin

``app`` og ``tests`` servicerne bruger samme application image, som bliver bygget ud fra ``Dockerfile``. ``db`` og ``pgadmin`` bliver startet fra images (``postgres:16`` og ``dpage/pgadmin4``) hentet fra Docker Hub.

Data fra databasen i ``db`` bliver gemt i ``postgres_data`` volume. ``pgadmin`` gemmer konfigurationsdata i ``pgadmin_data`` volume.

---
## Fil overview
- ``dmi_ohs`` mappen indeholder al applikationskode. Når Docker starter applikationen, starter den ``dmi_ohs/main.py``.
- ``tests`` mappen indeholder alle tests, som bliver kørt af ``tests`` servicen. Der er to undermapper:
	- ``tests/unit`` mappen indeholder alle unit tests, som er test af kode indenfor jeres applikation.
	- ``tests/integration`` mappen indeholder integration tests. Det er test af forbindelsen til andre systemer. Lige nu er der en test, der tjekker forbindelsen til Postgres databasen.
- ``.gitignore`` filen er en text fil, der beskriver hvilke filer og fil typer, der ikke skal skubbes til git.
- ``dockerignore`` filen er en text fil, der beskriver hvilke filer, der ikke skal kopieres ind i docker images
- ``requirements.txt`` er text fil, der lister alle de libraries, der skal bruges til at køre applikationen.
- ``requirements-dev.txt`` er en text fil, der lister alle de libraries, der skal bruges til at køre testene, men ikke bruges til at køre applikationen.
- ``.devcontainer`` mappen indeholder config filer til Dev Container
- ``pgadmin`` mappen indeholder config filer til pgAdmin

---
---
# Startup guide

## Lav .env fil
- I projektets root, skal du lave en ny fil, der hedder ``.env``, den indeholder miljø variabler for projektet. ``.env`` filen indeholder hemmeligheder som koder eller tokens, som ikke skal deles offentligt af sikkerhedshensyn. ``.env`` er derfor inkluderet i ``.gitignore``, så de ikke bliver synced med git.
- De følgende miljøvariable (environment variables) skal sættes i ``.env``. ``POSTGRES_HOST=db`` og ``POSTGRES_PORT=5432`` skal ikke ændres, men resten af værdierne er vilkårlige.

```
POSTGRES_DB=postgres_db

POSTGRES_USER=admin

POSTGRES_PASSWORD=password

POSTGRES_HOST=db

POSTGRES_PORT=5432

PGADMIN_USER_EMAIL=admin@example.com

PGADMIN_PASSWORD=password
```

---
## Dev container

En af udfordringerne med Docker, er at ens IDE ikke har adgang til ens dependencies og pakker. Det betyder, den kan vise fejl i ens kode pga. manglende installationer, selvom dette ikke vil være et problem ved runtime, da de der vil være installeret i ens container. Man kan heller ikke bruge intellisense fra ens pakker i IDE'en.

Løsningen er en Dev Container, som er en Docker container, hvor ens dependencies are installeret som man kan åbne VS Code i. For at åbne projektet i en dev container:
1. Installer ``Dev Containers`` extension i VS Code
2. Tryk ``ctrl`` + ``shift`` + ``p`` for at få command pallete frem
3. Brug kommandoen ``Dev Containers: Reopen in Container``
	- Dette skridt kan godt tage et stykke tid første gang
4. Nede i venstre hjørne af VS Code vil der nu være et blåt mærke, hvor der står ``Dev Container: ...`` op du har nu adgang til dine dependencies.
5. For at lukke dev containeren, åben command pallete (``ctrl`` + ``shift`` + ``p``) og brug kommandoen ``Dev Containers: Reopen Folder Locally``

---
## Start og stop applikationen

1. Sørg for at Docker Desktop er åben i baggrunden
2. Åben terminalen i projektets root mappe
3. Brug kommandoen ``docker compose up --build app``
	- ``postgres:16`` image bliver hentet fra Docker Hub *(ved første kørsel)*, og ``db`` servicen bliver startet
	- Application imaget bliver bygget ud fra ``Dockerfile``, og ``app`` servicen bliver startet
        - *(Imaget bliver kun genbygget, hvis der er sket ændringer, der nødvendiggør det på grund af caching.)*
4. Brug kommandoen ``docker compose down``
	- ``db`` og ``app`` servicerne bliver stoppet.

---
## Køre testene

1. Sørg for at Docker Desktop er åben i baggrunden.
2. Åben terminalen i projektets root,
3. Brug kommandoen ``docker compose run --build --rm tests``
	- ``postgres:16`` image bliver hentet fra Docker Hub *(ved første kørsel)*, og ``db`` servicen bliver startet.
	- Application imaget bliver bygget ud fra ``Dockerfile``, og ``tests`` servicen bliver startet
	- ``tests`` servicen lukker automatisk efter kørsel på grund af ``--rm`` flaget.
4. Brug kommandoen ``docker compose down``
	- ``db`` servicen bliver nu stoppet.
		- *(Den bliver automatisk startet, når ``tests`` servicen bliver startet, men den bliver ikke automatisk stoppet, da andre services, f.eks. ``app``, kan være afhængige af den.)*

---
## pgAdmin

pgAdmin er et værktøj til at administrere PostgreSQL-databaser. Det kan være praktisk til at visualisere ens database og konstruere queries.

Der er en pgAdmin container sat up i projektet. For at åbne den:
1. Åben terminallen i projektets root
2. Brug kommandoen ``docker compose up -d pgadmin``
3. Åben din browser og gå ind på http://localhost:8080/. Det kan godt tage lidt tid at få forbindelse
4. Login med pgAdmin credentials fra ``.env`` filen
5. Forbindelsen til databasen er allerede konfigureret. Når du connecter med databasen vil du blive promptet til at indtaste et password. Det er postgres passwordet fra ``.env`` filen

---
## Databaseskema

Databaseskemaet ligger i ``database/schema.sql``. Docker monterer filen i
PostgreSQLs ``/docker-entrypoint-initdb.d``-mappe, så PostgreSQL kører den
automatisk, første gang databasen oprettes.

Efter oprettelsen kører applikationen migrationsfilerne i
``database/migrations`` ved opstart. Tabellen ``schema_migrations`` holder
styr på, hvilke migrations der allerede er kørt, så hver migration kun
køres én gang. Nye ændringer til databasen skal derfor tilføjes som en ny,
nummereret ``.sql``-fil i stedet for at ændre en migration, der allerede er
kørt.

Skemaet består af:

- ``stations``: stationens stabile DMI-id og aktuelle metadata.
- ``parameters``: parameterbeskrivelser fra ``data/dmi-parameter-catalog.json``.
- ``parameter_codes``: forklaringer på kodede værdier, for eksempel
  vejrkoder.
- ``observations``: målinger i langt format, én række pr. station, parameter
  og tidspunkt.

Skemaet gemmer den aktuelle DMI-record pr. station. Hvis DMI returnerer flere
historiske records for samme ``stationId``, vælger ETL-processen den aktuelle
record, men gemmer dens gyldighedsdata og rå JSON for sporbarhed. Det passer
til projektets fokus på aktuelle miljøforhold.

Når der senere kommer måleudstyr inde i bygningen, kan der tilføjes en
generaliseret kilde- eller enhedstabel, så både DMI-stationer og indendørs
sensorer kan levere observationer.

``database/schema.sql`` bruges kun som bootstrap for en ny database. Et
eksisterende persistent ``postgres_data``-volume opdateres automatisk, når
app- eller tests-servicen starter. Tag altid backup før migrations, der
ændrer eller sletter eksisterende data.

---
---
# Libraries

Fordi projektet køres og udvikles i Docker containere, skal der ikke installeres nogen libraries lokalt. Istedet, skal de listes i ``requirements.txt`` filen, så bliver de automatisk inkluderet i ens Docker image. Når man har lagt et nyt library ind i ``requirements.txt`` er det en god ide at genbygge og genstarte ens dev container med command pallete kommandoerne:
- ``Dev Containers: Reopen Folder Locally``
- ``Dev Containers: Rebuild and Reopen in Container``

Det er forresten best practice at lave **version pinning** i sin ``requirements.txt`` fil. Det betyder at man istedet for at referere en pakke f.eks. ``pandas``, så refererer man en specifik version af pandas f.eks. ``pandas==3.0.5``. Det sikrer, at det samme version bliver brugt i hver build for consistency.

---
---
# Docker / Docker Compose kommandoer

- **Start ``app``:** ``docker compose up --build app``
- **Kør ``tests``:** ``docker compose run --build --rm tests``
- **Stop services:** ``docker compose down``
- **Stop services og slet volumes:** ``docker compose down -v``
- **Start ``pgadmin``:** ``docker compose up -d pgadmin``
- **Se alle containers:** ``docker compose ps -a``
- **Se alle images:** ``docker image ls``
- **Slet alle images:** ``docker image prune -a``
- **Se alle volumes:** ``docker volume ls -a``