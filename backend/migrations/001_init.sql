CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE routes (
    route_id    text PRIMARY KEY,
    short_name  text NOT NULL,
    long_name   text NOT NULL,
    color       char(6) NOT NULL,
    text_color  char(6) NOT NULL,
    sort_order  int NOT NULL
);

-- Parent stations. Platforms ("A27N"/"A27S") share their station's location.
CREATE TABLE stations (
    stop_id  text PRIMARY KEY,
    name     text NOT NULL,
    location geography(Point, 4326) NOT NULL,
    routes   text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX stations_location_idx ON stations USING gist (location);

-- One hop between consecutive stops on a line, with the scheduled travel time.
CREATE TABLE segments (
    route_id        text NOT NULL,
    from_stop       text NOT NULL,
    to_stop         text NOT NULL,
    typical_seconds int  NOT NULL,
    trips           int  NOT NULL,
    PRIMARY KEY (route_id, from_stop, to_stop)
);

-- Saved commutes. Riders are anonymous: the browser generates a client id and keeps it.
CREATE TABLE commutes (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL,
    route_id          text NOT NULL,
    stop_id           text NOT NULL,
    label             text NOT NULL,
    threshold_minutes int  NOT NULL DEFAULT 12 CHECK (threshold_minutes BETWEEN 2 AND 60),
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX commutes_client_idx ON commutes (client_id);
