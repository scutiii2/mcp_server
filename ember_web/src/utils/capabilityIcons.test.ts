import { describe, expect, it } from "vitest";
import { capabilityIcon, EXTENSION_ICON } from "./capabilityIcons";

const wrench = capabilityIcon("zzz");

describe("capabilityIcon", () => {
  it("picks an icon from the capability's name", () => {
    expect(capabilityIcon("pdf")).not.toEqual(wrench);
    expect(capabilityIcon("services")).not.toEqual(wrench);
    expect(capabilityIcon("pdf")).not.toEqual(capabilityIcon("services"));
  });

  it("also reads the label", () => {
    expect(capabilityIcon("x1", "Email tools")).toEqual(capabilityIcon("mail"));
  });

  it("falls back to the wrench for anything unrecognised", () => {
    expect(capabilityIcon("frobnicate", null)).toEqual(wrench);
    expect(wrench).not.toEqual(EXTENSION_ICON);
  });

  it("matches from the start of a word only", () => {
    expect(capabilityIcon("planet")).toEqual(wrench);
  });
});
