using UnityEngine;
using UnityEngine.UI;
using Unity.WebRTC;
using System;
using UnityEngine.Networking;
using System.Text;
using System.Collections;
using System.Linq;

public class WebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    [SerializeField] private string serverUrl = "https://34.133.108.164:8443";
    
    private RTCPeerConnection peerConnection;
    private MediaStream videoStream;
    private Texture2D currentTexture;
    private string connectionId;
    private System.Collections.Generic.List<RTCIceCandidate> pendingCandidates = new System.Collections.Generic.List<RTCIceCandidate>();
    
    // 証明書検証をスキップするための設定
    class AcceptAllCertificatesSignedWithAnyPublicKey : CertificateHandler
    {
        protected override bool ValidateCertificate(byte[] certificateData)
        {
            return true;
        }
    }
    
    void Start()
    {
        // SSL/TLS証明書の検証をスキップ
        Debug.Log("Starting WebRTC connection...");
        StartConnection();
    }

    void OnDestroy()
    {
        StopConnection();
    }

    private void StartConnection()
    {
        var configuration = new RTCConfiguration
        {
            iceServers = new[] { 
                new RTCIceServer { urls = new[] { "stun:stun.l.google.com:19302" } }
            }
        };

        peerConnection = new RTCPeerConnection(ref configuration);

        // ICE candidate イベントハンドラの設定
        peerConnection.OnIceCandidate = candidate =>
        {
            if (candidate == null) return;
            Debug.Log($"OnIceCandidate: {candidate.Candidate}");
            if (string.IsNullOrEmpty(connectionId))
            {
                Debug.Log("Connection ID not yet available, storing candidate");
                pendingCandidates.Add(candidate);
            }
            else
            {
                StartCoroutine(SendCandidate(candidate));
            }
        };

        peerConnection.OnIceConnectionChange = state =>
        {
            Debug.Log($"ICE Connection State: {state}");
        };

        peerConnection.OnConnectionStateChange = state =>
        {
            Debug.Log($"Connection State: {state}");
        };

        // Set up event handlers
        peerConnection.OnTrack = (RTCTrackEvent e) =>
        {
            if (e.Track is MediaStreamTrack track && track.Kind == TrackKind.Video)
            {
                videoStream = e.Streams.First(); // VideoStreamを取得
                var videoTrack = track as VideoStreamTrack;
                // VideoStreamTrackのイベントハンドラを設定
                videoTrack.OnVideoReceived += (Texture texture) =>
                {
                    if (texture is Texture2D tex2D)
                    {
                        // 前のテクスチャを破棄
                        if (currentTexture != null)
                        {
                            Destroy(currentTexture);
                        }

                        Debug.Log($"Received texture format: {tex2D.format}, size: {tex2D.width}x{tex2D.height}");
                        
                        // 元のテクスチャのピクセルデータを取得
                        var sourcePixels = tex2D.GetPixels32();
                        
                        // 新しいテクスチャを作成（明示的にRGBA32フォーマットを使用）
                        var correctedTex = new Texture2D(tex2D.width, tex2D.height, TextureFormat.RGBA32, false);
                        var newPixels = new Color32[sourcePixels.Length];
                        
                        // ピクセルデータを処理
                        for (int i = 0; i < sourcePixels.Length; i++)
                        {
                            var pixel = sourcePixels[i];
                            newPixels[i] = new Color32(
                                pixel.r,  // R
                                pixel.g,  // G
                                pixel.b,  // B
                                255      // A = 255 (完全な不透明)
                            );
                        }
                        
                        // 新しいピクセルデータを適用
                        correctedTex.SetPixels32(newPixels);
                        correctedTex.Apply();
                        
                        // 統計情報の計算
                        long[] sums = new long[3] { 0, 0, 0 };
                        long[] sumSquares = new long[3] { 0, 0, 0 };
                        int pixelCount = newPixels.Length;
                        
                        foreach (var pixel in newPixels)
                        {
                            // R, G, Bの値を収集
                            sums[0] += pixel.r;
                            sums[1] += pixel.g;
                            sums[2] += pixel.b;
                            
                            // 二乗和を計算
                            sumSquares[0] += pixel.r * pixel.r;
                            sumSquares[1] += pixel.g * pixel.g;
                            sumSquares[2] += pixel.b * pixel.b;
                        }
                        
                        // 平均と分散を計算
                        float[] means = new float[3];
                        float[] variances = new float[3];
                        
                        for (int c = 0; c < 3; c++)
                        {
                            means[c] = (float)sums[c] / pixelCount;
                            variances[c] = ((float)sumSquares[c] / pixelCount) - (means[c] * means[c]);
                        }
                        
                        float totalVariance = (variances[0] + variances[1] + variances[2]) / 3.0f;
                        
                        Debug.Log($"Color Means: R={means[0]:F3}, G={means[1]:F3}, B={means[2]:F3}");
                        Debug.Log($"Color Variance: {totalVariance:F3}");
                        
                        // テクスチャを保存して表示
                        currentTexture = correctedTex;
                        displayImage.texture = currentTexture;
                        displayImage.color = Color.white;
                    }
                    else
                    {
                        Debug.LogWarning("Texture is not Texture2D");
                        displayImage.texture = texture;
                    }
                    displayImage.color = Color.white; // Set alpha to 1
                };
            }
        };

        // Start negotiation
        StartCoroutine(Negotiate());
    }

    private IEnumerator Negotiate()
    {
        // Add transceivers (similar to client.js)
        var videoInit = new RTCRtpTransceiverInit { direction = RTCRtpTransceiverDirection.RecvOnly };
        var audioInit = new RTCRtpTransceiverInit { direction = RTCRtpTransceiverDirection.RecvOnly };
        peerConnection.AddTransceiver(TrackKind.Video, videoInit);
        peerConnection.AddTransceiver(TrackKind.Audio, audioInit);

        // Create and set local description
        var op = peerConnection.CreateOffer();
        yield return new WaitUntil(() => op.IsDone);
        
        if (op.IsError)
        {
            Debug.LogError($"Create offer failed: {op.Error.message}");
            yield break;
        }

        var desc = op.Desc;
        var setLocalDesc = peerConnection.SetLocalDescription(ref desc);
        yield return new WaitUntil(() => setLocalDesc.IsDone);

        if (setLocalDesc.IsError)
        {
            Debug.LogError($"Set local description failed: {setLocalDesc.Error.message}");
            yield break;
        }

        // Wait for ICE gathering to complete
        yield return new WaitUntil(() => peerConnection.GatheringState == RTCIceGatheringState.Complete);

        // Send offer to signaling server
        var offer = peerConnection.LocalDescription;
        var jsonOffer = JsonUtility.ToJson(new SignalingMessage
        {
            sdp = offer.sdp,
            type = offer.type.ToString().ToLower()
        });

        using (var request = new UnityWebRequest($"{serverUrl}/offer", "POST"))
        {
            // 証明書検証をスキップする設定を追加
            request.certificateHandler = new AcceptAllCertificatesSignedWithAnyPublicKey();
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonOffer);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Failed to send offer: {request.error}");
                yield break;
            }

            // Parse answer
            var response = JsonUtility.FromJson<SignalingMessage>(request.downloadHandler.text);
            connectionId = response.connectionId;  // Store the connection ID
            RTCSessionDescription answer = new RTCSessionDescription
            {
                type = (RTCSdpType)Enum.Parse(typeof(RTCSdpType), response.type, true),
                sdp = response.sdp
            };

            // Set remote description
            var setRemoteDesc = peerConnection.SetRemoteDescription(ref answer);
            yield return new WaitUntil(() => setRemoteDesc.IsDone);

            if (setRemoteDesc.IsError)
            {
                Debug.LogError($"Set remote description failed: {setRemoteDesc.Error.message}");
                yield break;
            }

            // Send any pending candidates now that we have the connection ID
            Debug.Log($"Sending {pendingCandidates.Count} pending candidates");
            foreach (var candidate in pendingCandidates)
            {
                StartCoroutine(SendCandidate(candidate));
            }
            pendingCandidates.Clear();
        }
    }

    private void StopConnection()
    {
        if (peerConnection != null)
        {
            peerConnection.Close();
            peerConnection.Dispose();
            peerConnection = null;
        }

        if (videoStream != null)
        {
            videoStream.Dispose();
            videoStream = null;
        }

        // テクスチャのクリーンアップ
        if (currentTexture != null)
        {
            Destroy(currentTexture);
            currentTexture = null;
        }
    }

    private IEnumerator SendCandidate(RTCIceCandidate candidate)
    {
        CandidateMessage candMsg = new CandidateMessage
        {
            candidate = candidate.Candidate,
            sdpMid = candidate.SdpMid,
            sdpMLineIndex = candidate.SdpMLineIndex ?? 0,
            connectionId = connectionId
        };
        var jsonCandidate = JsonUtility.ToJson(candMsg);

        using (var request = new UnityWebRequest($"{serverUrl}/candidate", "POST"))
        {
            request.certificateHandler = new AcceptAllCertificatesSignedWithAnyPublicKey();
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonCandidate);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Failed to send candidate: {request.error}");
                yield break;
            }
            // You can parse server response here if needed for remote candidate
        }
    }

    [Serializable]
    private class CandidateMessage
    {
        public string candidate;
        public string sdpMid;
        public int sdpMLineIndex;
        public string connectionId;
    }

    [Serializable]
    private class SignalingMessage
    {
        public string sdp;
        public string type;
        public string connectionId;
    }
}
