.PHONY: all build run clean deploy

all: deploy

build:
	docker compose -f docker-compose.yaml build

run:
	docker compose -f docker-compose.yaml up -d

clean:
	docker compose -f docker-compose.yaml down --rmi all

deploy: clean build run
