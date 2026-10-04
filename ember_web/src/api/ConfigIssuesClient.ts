import { apiRequest } from "./http";

export interface ConfigIssue {
  file: string;
  key: string;
  message: string;
}

export const configIssuesClient = {
  list: () => apiRequest<ConfigIssue[]>("GET", "/api/config-issues"),
};
