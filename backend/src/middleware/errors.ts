import type { ErrorRequestHandler, RequestHandler } from "express";

export const notFoundHandler: RequestHandler = (request, response) => {
  response.status(404).json({
    status: "error",
    error: {
      code: "NOT_FOUND",
      message: `No route is registered for ${request.method} ${request.path}.`,
    },
  });
};

export const errorHandler: ErrorRequestHandler = (error, request, response, _next) => {
  request.log.error({ err: error }, "Unhandled request error");
  response.status(500).json({
    status: "error",
    error: {
      code: "INTERNAL_SERVER_ERROR",
      message: "An unexpected server error occurred.",
    },
  });
};
