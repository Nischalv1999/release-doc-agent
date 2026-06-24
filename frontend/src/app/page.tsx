"use client";

import { useState } from "react";
import { ReleaseCard } from "@/components/ReleaseCard";
import { GeneratePanel } from "@/components/GeneratePanel";

const API_BASE = "http://localhost:8000/api";

interface Release {
  id: string;
  name: string;
  status: string;
  created_at: string;
  artifacts: {
    changelog: string;
    internal_release_notes: string;
    customer_release_notes: string;
    documentation_updates: Array<{
      doc_path: string;
      section: string;
      suggested_content: string;
      action: string;
    }>;
  };
  digest: Record<string, unknown>;
  review: Record<string, unknown>;
  evaluation: {
    hallucination_rate: number;
    ticket_coverage: number;
    doc_recommendation_accuracy: number;
    overall_score: number;
  };
  source_evidence: {
    commits: Array<Record<string, unknown>>;
    pull_requests: Array<Record<string, unknown>>;
    tickets: Array<Record<string, unknown>>;
    relevant_docs: Array<Record<string, unknown>>;
  };
}

export default function Home() {
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRelease, setSelectedRelease] = useState<Release | null>(null);

  const generateRelease = async (name: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/releases/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ release_name: name, use_mock_data: true }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Generation failed");
      }
      const release = await res.json();
      setReleases((prev) => [release, ...prev]);
      setSelectedRelease(release);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const approveRelease = async (
    id: string,
    edits: Partial<Release["artifacts"]>
  ) => {
    try {
      const res = await fetch(`${API_BASE}/releases/${id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(edits),
      });
      const updated = await res.json();
      setReleases((prev) => prev.map((r) => (r.id === id ? updated : r)));
      setSelectedRelease(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Approval failed");
    }
  };

  return (
    <div className="space-y-8">
      <GeneratePanel onGenerate={generateRelease} loading={loading} />

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          {error}
        </div>
      )}

      {selectedRelease && (
        <ReleaseCard
          release={selectedRelease}
          onApprove={approveRelease}
          onBack={() => setSelectedRelease(null)}
        />
      )}

      {!selectedRelease && releases.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-medium">Generated Releases</h2>
          {releases.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelectedRelease(r)}
              className="w-full text-left bg-white rounded-lg border p-4 hover:border-blue-300 transition"
            >
              <div className="flex justify-between items-center">
                <div>
                  <span className="font-medium">{r.name}</span>
                  <span className="ml-3 text-sm text-gray-500">
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                </div>
                <StatusBadge status={r.status} />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    review: "bg-yellow-100 text-yellow-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
    needs_revision: "bg-orange-100 text-orange-800",
  };
  return (
    <span
      className={`px-2 py-1 rounded-full text-xs font-medium ${colors[status] || "bg-gray-100"}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}
