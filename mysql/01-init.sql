CREATE TABLE configuration
(
    id INT NOT NULL AUTO_INCREMENT,
    repository VARCHAR(500) NOT NULL,
    scan_code ENUM('true', 'false') DEFAULT 'true' NOT NULL,
    scan_secrets ENUM('true', 'false') DEFAULT 'true' NOT NULL,
    scan_dependabot ENUM('true', 'false') DEFAULT 'true' NOT NULL,
    minimum_severity ENUM('critical', 'high', 'medium', 'low') NOT NULL DEFAULT ('high')
)