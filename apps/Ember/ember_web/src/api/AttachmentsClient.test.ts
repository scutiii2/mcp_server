import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { attachmentsClient } from "./AttachmentsClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("attachmentsClient.table", () => {
  it("posts the file as base64 to the table endpoint", async () => {
    await attachmentsClient.table(new File(["a,b\n1,2\n"], "sales.csv"));

    expect(request).toHaveBeenCalledExactlyOnceWith("POST", "/api/attachments/table", {
      filename: "sales.csv",
      data: btoa("a,b\n1,2\n"),
    });
  });

  it("refuses a file over the limit before uploading it", async () => {
    const big = new File(["x"], "big.csv");
    Object.defineProperty(big, "size", { value: 16 * 1024 * 1024 });

    await expect(attachmentsClient.table(big)).rejects.toThrow("Too large");
    expect(request).not.toHaveBeenCalled();
  });
});


describe("attachmentsClient.pdf", () => {
  it("uploads originals as base64 to the PDF endpoint", async () => {
    await attachmentsClient.pdf(new File(["%PDF-original"], "scan.pdf"));
    expect(request).toHaveBeenCalledExactlyOnceWith("POST", "/api/attachments/pdf", {
      filename: "scan.pdf", data: btoa("%PDF-original"),
    });
  });
  it("rejects oversized originals before uploading", async () => {
    const big = new File(["x"], "scan.pdf");
    Object.defineProperty(big, "size", { value: 16 * 1024 * 1024 });
    await expect(attachmentsClient.pdf(big)).rejects.toThrow("Too large");
    expect(request).not.toHaveBeenCalled();
  });
});
