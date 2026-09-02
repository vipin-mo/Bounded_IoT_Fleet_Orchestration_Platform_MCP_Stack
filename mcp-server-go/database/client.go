package database

import (
	"context"

	"github.com/redis/go-redis/v9"
)

// Shared database structures available to handlers
var RedisClient *redis.Client
var Ctx = context.Background()

// InitRedis establishes the connection pool to the local Docker Redis instance
func InitRedis() error {
	RedisClient = redis.NewClient(&redis.Options{
		Addr:     "localhost:6379", // Points to the exposed container port mapping
		Password: "",               // No security authentication configured for mock environment
		DB:       0,                // Read from default storage index
	})

	// Execute an instant ping check to prevent runtime database execution panics
	_, err := RedisClient.Ping(Ctx).Result()
	return err
}
