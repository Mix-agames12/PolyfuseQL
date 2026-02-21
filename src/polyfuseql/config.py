"""
polyfuseql.config
~~~~~~~~~~~~~~~~~~~~~
Centralized configuration management using Pydantic settings.

This module defines a unified, type-validated configuration model for all
application settings, including database connections and Spark parameters.
It loads settings from environment variables and a .env file, providing a
single source of truth throughout the application.
"""

import logging
import os
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseModel):
    user: str = os.getenv("POSTGRES_USER", "tpch")
    password: str = os.getenv("POSTGRES_PASSWORD", "tpch")
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", 5432))
    db: str = os.getenv("POSTGRES_DB", "tpch")


class RedisSettings(BaseModel):
    host: str = os.getenv("REDIS_HOST", "localhost")
    port: int = int(os.getenv("REDIS_PORT", 6379))
    db: int = 0
    password: str = os.getenv("REDIS_PASSWORD", "tpch")
    data_type: str = "string"


class Neo4jSettings(BaseModel):
    uri: str = "bolt://neo4j:7687"
    user: str = "neo4j"
    password: str = "password"
    host: str = "localhost"
    port: int = 7687

class MongoDbSettings(BaseModel):
    user: str = os.getenv("MONGO_INITDB_ROOT_USERNAME", "root")
    password: str = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "example")
    host: str = os.getenv("MONGO_HOST", "mongodb")
    port: int = int(os.getenv("MONGO_PORT", 27017))
    db: str = os.getenv("MONGO_DB_NAME", "tpch")


class CassandraAuthSettings(BaseModel):
    """
    Defines settings for connecting to the separate auth microservice.
    The port is based on the host mapping from 'docker ps' (3001->3001).
    """

    url: str = "http://polyfuseql_cassandra_translator_auth:3001"
    cedula: str = "admin"
    nombre: str = "Admin User"
    password: str = "admin123"


class CassandraSettings(BaseModel):
    user: str | None = "cassandra"
    password: str | None = "cassandra"
    host: str = "cassandra"
    port: int = 9043
    keyspace: str = "mykeyspace"
    auth: CassandraAuthSettings = Field(default_factory=CassandraAuthSettings)


class SparkSettings(BaseModel):
    master_url: str = "local[*]"
    app_name_prefix: str = "PolyFuseQL-TPCH-Benchmark"
    driver_memory: str = "4g"
    executor_memory: str = "3g"
    cores_max: str = "48"
    shuffle_partitions: str = "144"
    network_timeout: str = "8000s"
    executor_heartbeat_interval: str = "60s"
    neo4j_spark_jar_path: str = ""
    redis_spark_jar_package: str = "com.redis.spark:spark-redis_2.13:3.3.0"


class AppSettings(BaseSettings):
    """
    Defines the complete configuration for the application, loading values
    from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        # Changed to "_" so variables like POSTGRES_HOST map to postgres.host
        env_nested_delimiter="_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)

    # added validation_alias="mongo" so 'MONGO_HOST' env
    # var maps to this 'mongodb' field
    mongodb: MongoDbSettings = Field(
        default_factory=MongoDbSettings, validation_alias="mongo"
    )

    cassandra: CassandraSettings = Field(default_factory=CassandraSettings)
    spark: SparkSettings = Field(default_factory=SparkSettings)

    mongo_translator_url: str = "http://mongo-translator-api:5000"
    cassandra_translator_url: str = "http://polyfuseql_cassandra_translator:3000"

    # Application-specific Settings
    polyfuseql_schema_path: Path = Path("schemas.json")

    def __init__(self, **data):
        super().__init__(**data)
        # Logging moved to __init__ so it runs after data is loaded
        logging.info(f"Loaded MongoDB Settings: {self.mongodb}")


# Singleton instance to be used across the application
settings = AppSettings()
