import type { Config, Context } from "@netlify/functions";
import { createNightNodeHandler } from "./_shared/night_node.mjs";

const night = createNightNodeHandler({
  sourceDir: new URL("./_python/", import.meta.url),
  platform: "netlify",
  platformInfo(context: Context | undefined) {
    const geo = context?.geo;
    const subdivision = geo?.subdivision;
    return {
      client_ip: context?.ip,
      request_id: context?.requestId,
      country: geo?.country?.code,
      city: geo?.city,
      region: typeof subdivision === "string" ? subdivision : subdivision?.code,
      timezone: geo?.timezone,
      latitude: geo?.latitude,
      longitude: geo?.longitude,
    };
  },
});

export default async (req: Request, context: Context) => night(req, context);

export const config: Config = {
  path: "/*",
};
