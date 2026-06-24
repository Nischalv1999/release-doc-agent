"use client";

import { useState } from "react";

interface Props {
  onGenerate: (name: string) => void;
  loading: boolean;
}

export function GeneratePanel({ onGenerate, loading }: Props) {
  const [name, setName] = useState("v2.4.0");

  return (
    <div className="bg-white rounded-lg border p-6">
      <h2 className="text-lg font-medium mb-4">Generate Release Documentation</h2>
      <p className="text-sm text-gray-600 mb-4">
        Analyzes git commits, pull requests, and Jira tickets to automatically generate
        changelogs, release notes, and documentation update suggestions.
      </p>
      <div className="flex gap-3">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Release name (e.g., v2.4.0)"
          className="flex-1 px-3 py-2 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={() => onGenerate(name)}
          disabled={loading || !name.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <Spinner /> Generating...
            </span>
          ) : (
            "Generate"
          )}
        </button>
      </div>
      {loading && (
        <p className="mt-3 text-sm text-gray-500">
          Running agent pipeline: Digest → Plan → Retrieve → Write → Review...
        </p>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
      <circle
        className="opacity-25"
        cx="12" cy="12" r="10"
        stroke="currentColor" strokeWidth="4" fill="none"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
